import random
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.engine.game import ActionResult, GameSession
from backend.app.main import create_app
from backend.app.models.common import Direction, Position
from backend.app.models.story import (
    GrantRivalStarterCommand,
    GrantStarterCommand,
    PositionTrigger,
    SelectRivalStarterCommand,
    SelectStarterCommand,
    StartBattleCommand,
    StartTrigger,
    StoryNode,
)
from backend.app.source.pokered import PokeredSource
from backend.app.source.pokered.battle_text import battle_text
from backend.app.source.pokered.parsers import ParseError


class CountingRandom:
    def __init__(self, seed: int = 1) -> None:
        self.random = random.Random(seed)
        self.draws = 0

    def __call__(self) -> int:
        self.draws += 1
        return self.random.getrandbits(8)


@pytest.fixture(scope="module")
def source():  # type: ignore[no-untyped-def]
    return PokeredSource(Path(__file__).resolve().parents[1] / "external/pokered")


def fixture_adventure(source: PokeredSource, species: str = "CHARMANDER"):  # type: ignore[no-untyped-def]
    world, story = source.build_world(), source.build_story()
    position = Position(x=5, y=3)
    world = world.model_copy(update={"start_map": "OAKS_LAB", "player_spawn": position})
    key = next(
        key for key, starter in story.starters.items() if starter.species.constant == species
    )
    story = story.model_copy(
        update={
            "start_map": "OAKS_LAB",
            "start_position": position,
            "start_facing": Direction.SOUTH,
            "nodes": (
                StoryNode(
                    id="grant",
                    trigger=StartTrigger(),
                    provenance=story.provenance,
                    commands=(
                        SelectStarterCommand(starter_key=key),
                        GrantStarterCommand(starter_key=key),
                        SelectRivalStarterCommand(starter_key=key),
                        GrantRivalStarterCommand(starter_key=key),
                    ),
                ),
                StoryNode(
                    id="battle",
                    trigger=PositionTrigger(map_id="OAKS_LAB", x=5, y=4),
                    provenance=story.provenance,
                    commands=(StartBattleCommand(),),
                ),
            ),
        }
    )
    return world, story


def battle_view(session: GameSession):  # type: ignore[no-untyped-def]
    return session.response(None, ActionResult("connected")).state.battle


def ready_battle(source: PokeredSource, species: str = "CHARMANDER", seed: int = 1):  # type: ignore[no-untyped-def]
    world, story = fixture_adventure(source, species)
    rng = CountingRandom(seed)
    session = GameSession(world, story, source.build_battle(), rng)
    assert rng.draws == 2  # AddPartyMon grant, before battle entry.
    assert session.move(Direction.SOUTH).action == "battle_started"
    view = battle_view(session)
    assert view is not None and view.batch is not None and view.action_token is None
    assert session.acknowledge_battle(view.id, view.batch.id).action == "battle_presented"
    return session, rng


@pytest.mark.parametrize("species", ["CHARMANDER", "SQUIRTLE", "BULBASAUR"])
def test_grant_once_pairings_and_deepcopy(source: PokeredSource, species: str) -> None:
    session, rng = ready_battle(source, species)
    assert rng.draws == 2
    copied = deepcopy(session)
    view = battle_view(session)
    assert view.player.species == species
    assert view.rival.species == source.build_battle().rival_for(species).rival_species
    before = session._story.player_pokemon.dvs  # type: ignore[union-attr]
    assert session.battle_action(view.id, view.action_token, 0).action == "battle_turn"
    assert session._story.player_pokemon.dvs == before  # type: ignore[union-attr]
    assert battle_view(copied) == view
    assert copied._rng.draws == 2  # type: ignore[attr-defined]


def test_invalid_stale_and_presentation_gate_preserve_rng(source: PokeredSource) -> None:
    session, rng = ready_battle(source)
    view = battle_view(session)
    version, draws = session.state_version, rng.draws
    for battle_id, token, slot in (
        ("old", view.action_token, 0),
        (view.id, "old", 0),
        (view.id, view.action_token, 3),
        (view.id, view.action_token, None),
    ):
        assert session.battle_action(battle_id, token, slot).action == "blocked"
        assert (session.state_version, rng.draws) == (version, draws)
    assert session.battle_action(view.id, view.action_token, 0).action == "battle_turn"
    after, draws = battle_view(session), rng.draws
    assert after.player.moves[0].pp == view.player.moves[0].pp - 1
    assert after.batch.frames[-1].player_hp == after.player.hp
    assert after.batch.frames[-1].rival_hp == after.rival.hp
    assert session.battle_action(view.id, view.action_token, 0).action == "blocked"
    assert session.move(Direction.SOUTH).action == "blocked"
    assert session.interact().action == "blocked"
    assert session.acknowledge_battle(view.id, "old").action == "blocked"
    assert rng.draws == draws
    assert session.acknowledge_battle(after.id, after.batch.id).action == "battle_presented"
    assert session.acknowledge_battle(after.id, after.batch.id).action == "blocked"
    assert battle_view(session).action_token != view.action_token


@pytest.mark.parametrize("slot,outcome", [(0, "player_win"), (1, "player_loss")])
def test_terminal_result_waits_for_ack_then_returns_to_story(
    source: PokeredSource, slot: int, outcome: str
) -> None:
    session, rng = ready_battle(source, seed=3)
    for _ in range(150):
        view = battle_view(session)
        selected = slot if view.player.moves[slot].pp else (0 if view.player.moves[0].pp else None)
        assert session.battle_action(view.id, view.action_token, selected).action == "battle_turn"
        after = battle_view(session)
        if after.outcome != "ongoing":
            break
        assert session.acknowledge_battle(after.id, after.batch.id).action == "battle_presented"
    terminal = battle_view(session)
    assert terminal.outcome == outcome
    assert terminal.action_token is None
    frames = terminal.batch.frames
    if outcome == "player_win":
        grown = next(index for index, frame in enumerate(frames) if frame.show_stats)
        assert grown >= 2
        assert all(frame.player_level == 5 for frame in frames[:grown])
        assert all(frame.player_level == 6 for frame in frames[grown:])
        assert frames[grown - 1].text == "CHARMANDER gained\n70 EXP. Points!"
        assert frames[grown].text == "CHARMANDER grew\nto level 6!"
        assert frames[-1].text == "RED got ¥175\nfor winning!"
        assert terminal.player.experience == 205
        assert terminal.player.max_hp == frames[grown].player_max_hp
        assert terminal.player.max_hp > frames[grown - 1].player_max_hp
        assert session._story.party[0].level == 6
    else:
        assert frames[-1].text == "BLUE: Yeah! Am\nI great or what?"
        assert all(not frame.show_stats and frame.player_level == 5 for frame in frames)
        assert terminal.player.experience == 135
        assert not any("blacked" in frame.text for frame in frames)
    assert "EVENT_BATTLED_RIVAL_IN_OAKS_LAB" not in session._story.flags  # type: ignore[union-attr]
    draws = rng.draws
    assert session.battle_action(view.id, "old", 0).action == "blocked"
    assert rng.draws == draws
    assert session.response(None, ActionResult("connected")).state.control_mode == "battle"
    assert session.acknowledge_battle(terminal.id, terminal.batch.id).action == "battle_presented"
    assert battle_view(session) is None
    assert session.money == (3175 if outcome == "player_win" else 3000)
    assert session.acknowledge_battle(terminal.id, terminal.batch.id).action == "blocked"
    assert session.response(None, ActionResult("connected")).state.control_mode == "free"


def test_websocket_battle_replay_and_changed_payload(source: PokeredSource) -> None:
    world, story = fixture_adventure(source)
    with (
        TestClient(create_app(world=world, story=story, battle=source.build_battle())) as client,
        client.websocket_connect("/ws/game") as socket,
    ):
        socket.receive_json()
        socket.send_json(
            {"type": "move", "request_id": "start", "direction": "south", "continued": False}
        )
        initial = socket.receive_json()["state"]["battle"]
        socket.send_json(
            {
                "type": "acknowledge_battle",
                "request_id": "ack",
                "battle_id": initial["id"],
                "batch_id": initial["batch"]["id"],
            }
        )
        ready = socket.receive_json()["state"]["battle"]
        action = {
            "type": "battle_action",
            "request_id": "turn",
            "battle_id": ready["id"],
            "action_token": ready["action_token"],
            "slot": 0,
        }
        socket.send_json(action)
        result = socket.receive_json()
        socket.send_json(action)
        assert socket.receive_json() == result
        socket.send_json({**action, "slot": 1})
        assert socket.receive_json()["type"] == "error"
        # Evict the request replay cache; the old action token still blocks it.
        for index in range(257):
            socket.send_json({"type": "interact", "request_id": f"blocked-{index}"})
            assert socket.receive_json()["action"] == "blocked"
        socket.send_json(action)
        blocked = socket.receive_json()
        assert blocked["action"] == "blocked"
        assert blocked["state_version"] == result["state_version"]


def test_assets_are_only_six_starter_files(source: PokeredSource) -> None:
    source.build_battle()
    with TestClient(create_app(world=source.build_world(), source=source)) as client:
        for name in ("bulbasaur", "charmander", "squirtle"):
            assert client.get(f"/source-assets/pokemon-front/{name}.png").status_code == 200
            assert client.get(f"/source-assets/pokemon-back/{name}b.png").status_code == 200
        for path in (
            "pokemon-front/pikachu",
            "pokemon-back/charmander",
            "bad/bulbasaur",
            "pokemon-front/%2e%2e%2fREADME",
        ):
            assert client.get(f"/source-assets/{path}.png").status_code == 404


def test_battle_text_rejects_unknown_dynamic_controls() -> None:
    assert (
        battle_text('_Test::\n text_ram wTrainerName\n line "wants!"\n prompt\n', "_Test")
        == "<RIVAL>\nwants!"
    )
    with pytest.raises(ParseError):
        battle_text("_Test::\n text_ram wUnknown\n prompt\n", "_Test")
