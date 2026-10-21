"""Progression arithmetic and source-script continuation at the terminal ack boundary."""

from pathlib import Path

import pytest

from backend.app.engine.battle_session import BattleSession
from backend.app.engine.game import ActionResult, GameSession
from backend.app.engine.pokemon import (
    award_battle_experience,
    calculate_starter_stats,
    create_rival_battle,
    experience_at_level,
    realize_starter,
)
from backend.app.models.battle import BattleDefinition, DeterminantValues, StatExperience
from backend.app.models.common import Direction, Position
from backend.app.models.protocol import PlayerState
from backend.app.models.story import SetActorCommand, StartBattleCommand
from backend.app.source.pokered import PokeredSource


@pytest.fixture(scope="module")
def source() -> PokeredSource:
    return PokeredSource(Path(__file__).resolve().parents[1] / "external/pokered")


@pytest.mark.parametrize(
    "species,gain,total", [("CHARMANDER", 70, 205), ("BULBASAUR", 69, 204), ("SQUIRTLE", 67, 202)]
)
def test_all_starters_award_source_experience(
    source: PokeredSource, species: str, gain: int, total: int
) -> None:
    definition = source.build_battle()
    state = create_rival_battle(
        definition, realize_starter(definition, species, definition.rival_dvs)
    )
    state = state.model_copy(
        update={"rival": state.rival.model_copy(update={"hp": 0}), "outcome": "player_win"}
    )
    original = state.model_dump_json()
    result = award_battle_experience(definition, state)
    assert state.model_dump_json() == original
    assert result.player.experience - state.player.experience == gain
    assert (result.player.experience, result.player.level) == (total, 6)
    foe = definition.species_named(state.rival.species)
    assert result.player.stat_experience.model_dump() == foe.base_stats.model_dump()
    assert result.player.hp - state.player.hp == result.player.stats.hp - state.player.stats.hp
    assert result.player.moves == state.player.moves
    assert result.player.dvs == state.player.dvs
    assert [experience_at_level(definition, level) for level in (5, 6, 7)] == [135, 179, 236]
    loss = state.model_copy(
        update={"player": state.player.model_copy(update={"hp": 0}), "outcome": "player_loss"}
    )
    assert award_battle_experience(definition, loss) is loss


def test_stat_bonus_ceil_root_and_caps(source: PokeredSource) -> None:
    definition = source.build_battle().species_named("CHARMANDER")
    dvs = DeterminantValues(attack_defense=0, speed_special=0)
    # ceil(sqrt(10))//4 = 1, unlike floor(sqrt(10))//4 = 0.
    assert calculate_starter_stats(definition, dvs, 100, StatExperience(attack=10)).attack == 110
    assert calculate_starter_stats(definition, dvs, 100, StatExperience(attack=9)).attack == 109
    assert calculate_starter_stats(definition, dvs, 100, StatExperience(attack=65535)).attack == 172
    large = definition.model_copy(
        update={"base_stats": definition.base_stats.model_copy(update={"attack": 999})}
    )
    assert calculate_starter_stats(large, dvs, 100, StatExperience(attack=65535)).attack == 999


def postbattle_session(
    source: PokeredSource, x: int, outcome: str, species: str = "CHARMANDER"
) -> GameSession:
    definition = source.build_battle()
    session = GameSession(source.build_world(), source.build_story(), definition, lambda: 0)
    runner = session._story
    assert runner is not None
    runner.map_id = "OAKS_LAB"
    runner.player = PlayerState(
        position=Position(x=x, y=6), facing=Direction.SOUTH, sprite=runner.player.sprite
    )
    runner.control_mode = "battle"
    runner.has_starter = True
    starter_key = next(
        key
        for key, starter in runner.definition.starters.items()
        if starter.species.constant == species
    )
    runner._select_starter(starter_key)
    runner._grant_starter(starter_key)
    runner._select_rival_starter(starter_key)
    runner._grant_rival_starter(starter_key)
    runner.flags.update({"EVENT_GOT_STARTER", "EVENT_OAK_ASKED_TO_CHOOSE_MON"})
    runner._set_actor(SetActorCommand(map_id="OAKS_LAB", actor_id="OAKSLAB_OAK1", visible=True))
    battle_node = next(
        node for node in runner.definition.nodes if node.id == "rival_battle_boundary"
    )
    command = next(
        command for command in battle_node.commands if isinstance(command, StartBattleCommand)
    )
    runner._battle_continuations = command.continuations
    battle = BattleSession(
        definition,
        realize_starter(definition, species, definition.rival_dvs),
        runner.world.text_variables,
    )
    player = battle.state.player.model_copy(
        update={
            "hp": 2 if outcome == "player_win" else 0,
            "moves": tuple(move.model_copy(update={"pp": 1}) for move in battle.state.player.moves),
        }
    )
    rival = battle.state.rival.model_copy(update={"hp": 0 if outcome == "player_win" else 5})
    battle.state = award_battle_experience(
        definition,
        battle.state.model_copy(update={"player": player, "rival": rival, "outcome": outcome}),
    )
    runner.sync_player_pokemon(battle.state.player)
    session._battle = battle
    runner._set_actor(
        SetActorCommand(map_id="OAKS_LAB", actor_id="OAKSLAB_RIVAL", position=Position(x=x, y=5))
    )
    return session


@pytest.mark.parametrize("outcome", ["player_win", "player_loss"])
@pytest.mark.parametrize("x,side", [(4, Direction.EAST), (5, Direction.WEST)])
@pytest.mark.parametrize("species", ["CHARMANDER", "BULBASAUR", "SQUIRTLE"])
def test_ack_heals_then_farewell_departure_and_no_retrigger(
    source: PokeredSource, x: int, side: Direction, outcome: str, species: str
) -> None:
    session = postbattle_session(source, x, outcome, species)
    battle = session._battle
    assert battle is not None and battle.batch is not None
    terminal_batch_id = battle.batch.id
    terminal_player = battle.state.player
    win_stats = {
        "CHARMANDER": (21, 12, 11, 13, 12),
        "BULBASAUR": (22, 12, 11, 11, 13),
        "SQUIRTLE": (22, 11, 13, 11, 12),
    }
    loss_stats = {
        "CHARMANDER": (19, 11, 10, 12, 10),
        "BULBASAUR": (20, 10, 10, 10, 12),
        "SQUIRTLE": (20, 10, 12, 10, 10),
    }
    assert (
        tuple(terminal_player.stats.model_dump().values())
        == (win_stats if outcome == "player_win" else loss_stats)[species]
    )
    assert terminal_player.experience == (
        {"CHARMANDER": 205, "BULBASAUR": 204, "SQUIRTLE": 202}[species]
        if outcome == "player_win"
        else 135
    )
    assert terminal_player.level == (6 if outcome == "player_win" else 5)
    assert terminal_player.dvs == DeterminantValues(attack_defense=152, speed_special=136)
    expected_ev = (
        battle.definition.species_named(battle.state.rival.species).base_stats.model_dump()
        if outcome == "player_win"
        else StatExperience().model_dump()
    )
    assert terminal_player.stat_experience.model_dump() == expected_ev
    assert session.money == 3000
    assert session.acknowledge_battle(battle.id, "stale").action == "blocked"
    assert "EVENT_BATTLED_RIVAL_IN_OAKS_LAB" not in session._story.flags
    assert session.acknowledge_battle(battle.id, battle.batch.id).action == "dialog_opened"
    runner = session._story
    assert runner is not None and runner.player_pokemon is not None
    assert session._battle is None
    assert runner.player_pokemon.hp == runner.player_pokemon.stats.hp
    assert [move.pp for move in runner.player_pokemon.moves] == [
        35,
        30 if species == "SQUIRTLE" else 40,
    ]
    assert runner.party[0].level == terminal_player.level
    assert runner.player_pokemon == terminal_player.model_copy(
        update={
            "hp": terminal_player.stats.hp,
            "moves": realize_starter(battle.definition, species, terminal_player.dvs).moves,
        }
    )
    assert "EVENT_BATTLED_RIVAL_IN_OAKS_LAB" in runner.flags
    assert runner.player.facing == Direction.NORTH
    assert runner.dialog.interaction_id == "rival_farewell"
    farewell = session.response(None, ActionResult("connected"))
    healed = runner.player_pokemon
    assert session.acknowledge_battle(battle.id, terminal_batch_id).action == "blocked"
    assert session.response(None, ActionResult("connected")) == farewell
    assert runner.player_pokemon == healed
    while runner.dialog is not None:
        session.interact()
    assert runner.player.facing == side
    assert runner.movement_cue.tracks[0].steps == (side,)
    session.acknowledge_cue(runner.movement_cue.id)
    assert runner.player.facing == side
    session.acknowledge_cue(runner.movement_cue.id)
    assert runner.player.facing == Direction.SOUTH
    assert runner.movement_cue.tracks[0].steps == (Direction.SOUTH,) * 4
    session.acknowledge_cue(runner.movement_cue.id)
    assert runner.control_mode == "free"
    assert not next(
        actor for actor in runner.map_state().actors if actor.id == "OAKSLAB_RIVAL"
    ).visible
    assert runner.after_move() is None
    assert session.money == (3175 if outcome == "player_win" else 3000)
    assert session.acknowledge_battle(battle.id, terminal_batch_id).action == "blocked"
    assert session.response(None, ActionResult("connected")).state.battle is None

    # Use real interactions after the source continuation, including the remaining ball.
    oak = next(actor for actor in runner.map_state().actors if actor.id == "OAKSLAB_OAK1")
    runner.player = runner.player.model_copy(
        update={"position": oak.position.moved(Direction.SOUTH), "facing": Direction.NORTH}
    )
    assert session.interact().action == "dialog_opened"
    assert runner.dialog.pages == ["OAK: RED,\nraise your young\nPOKéMON by making\nit fight!"]
    while runner.dialog is not None:
        session.interact()
    ball = next(
        actor for actor in runner.map_state().actors if "POKE_BALL" in actor.id and actor.visible
    )
    runner.player = runner.player.model_copy(
        update={"position": ball.position.moved(Direction.SOUTH), "facing": Direction.NORTH}
    )
    assert session.interact().action == "dialog_opened"
    assert runner.dialog.pages == ["That's PROF.OAK's\nlast POKéMON!"]
    assert runner.choice is None
    while runner.dialog is not None:
        session.interact()
    runner.player = runner.player.model_copy(
        update={"position": Position(x=5, y=11), "facing": Direction.SOUTH}
    )
    assert session.move(Direction.SOUTH).action == "transitioned"
    assert session.map_id == "PALLET_TOWN"
    assert session.move(Direction.NORTH).action == "turned"
    assert session.move(Direction.NORTH, continued=True).action == "transitioned"
    assert session.map_id == "OAKS_LAB"
    assert runner.after_move() is None
    assert runner.control_mode == "free"
    assert not next(
        actor for actor in runner.map_state().actors if actor.id == "OAKSLAB_RIVAL"
    ).visible
    assert runner.player_pokemon == healed
    assert session.money == (3175 if outcome == "player_win" else 3000)


def test_stat_experience_saturates(source: PokeredSource) -> None:
    definition: BattleDefinition = source.build_battle()
    session = postbattle_session(source, 4, "player_win")
    state = session._battle.state
    player = state.player.model_copy(
        update={
            "stat_experience": StatExperience(**dict.fromkeys(StatExperience.model_fields, 65534))
        }
    )
    result = award_battle_experience(definition, state.model_copy(update={"player": player}))
    assert set(result.player.stat_experience.model_dump().values()) == {65535}
