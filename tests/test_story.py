from __future__ import annotations

from collections import deque

import pytest
from pydantic import ValidationError

from backend.app.engine.game import ActionResult, GameSession
from backend.app.models.common import Direction, Position
from backend.app.models.map import TextInteraction, WorldDefinition
from backend.app.models.story import ActorState, StoryDefinition
from backend.app.source.pokered.pallet_story import compile_warp_interrupted_movement
from backend.app.source.pokered.parsers import (
    ParseError,
    parse_movement,
    parse_movement_sequence,
    parse_new_game_warp,
    parse_rgbds_constants,
    parse_simulated_joypad_rle,
)


def complete_direction(session: GameSession, direction: Direction) -> ActionResult:
    result = session.move(direction, continued=False)
    if result.action == "turned":
        result = session.move(direction, continued=True)
    return result


def snapshot(session: GameSession):  # type: ignore[no-untyped-def]
    return session.response(None, ActionResult("connected")).state


def drain_dialog(session: GameSession) -> ActionResult:
    result = ActionResult("dialog_closed")
    while session.dialog is not None:
        result = session.interact()
    return result


def drain_current_dialog(session: GameSession) -> ActionResult:
    assert session.dialog is not None
    interaction_id = session.dialog.interaction_id
    result = ActionResult("dialog_closed")
    while session.dialog is not None and session.dialog.interaction_id == interaction_id:
        result = session.interact()
    return result


def choose(session: GameSession, intent: str) -> ActionResult:
    current = snapshot(session).choice
    assert current is not None
    return session.choose(current.instance_id, intent)


def walk_to(session: GameSession, world: WorldDefinition, target: Position) -> ActionResult:
    map_definition = world.maps[session.map_id]
    start = session.player.position
    actors = {
        (actor.position.x, actor.position.y)
        for actor in snapshot(session).map.actors
        if actor.visible and actor.position != target
    }
    queue: deque[tuple[Position, list[Direction]]] = deque([(start, [])])
    seen = {(start.x, start.y)}
    found: list[Direction] | None = None
    for_position = {
        Direction.NORTH: (0, -1),
        Direction.SOUTH: (0, 1),
        Direction.WEST: (-1, 0),
        Direction.EAST: (1, 0),
    }
    while queue:
        position, path = queue.popleft()
        if position == target:
            found = path
            break
        for direction, (dx, dy) in for_position.items():
            candidate = Position(x=position.x + dx, y=position.y + dy)
            key = (candidate.x, candidate.y)
            if (
                key not in seen
                and key not in actors
                and map_definition.contains(candidate)
                and map_definition.is_walkable(candidate)
            ):
                seen.add(key)
                queue.append((candidate, [*path, direction]))
    assert found is not None
    result = ActionResult("moved")
    for direction in found:
        result = complete_direction(session, direction)
        if result.action not in {"moved", "transitioned"}:
            break
    return result


def canonical_lab_session(
    world: WorldDefinition, story: StoryDefinition, *, column: int = 10
) -> GameSession:
    session = GameSession(world, story)
    assert session.map_id == "REDS_HOUSE_2F"
    assert session.player == snapshot(session).player
    assert session.player.position == Position(x=3, y=6)
    assert session.player.facing == Direction.NORTH
    assert snapshot(session).party == []
    assert snapshot(session).flags == []

    walk_to(session, world, Position(x=7, y=1))
    assert session.map_id == "REDS_HOUSE_1F"
    walk_to(session, world, Position(x=2, y=7))
    assert complete_direction(session, Direction.SOUTH).action == "transitioned"
    assert session.map_id == "PALLET_TOWN"

    if column == 11:
        walk_to(session, world, Position(x=11, y=2))
        intercept = complete_direction(session, Direction.NORTH)
    else:
        intercept = walk_to(session, world, Position(x=column, y=1))
    assert intercept.action == "dialog_opened"
    assert "EVENT_OAK_APPEARED_IN_PALLET" in snapshot(session).flags
    assert snapshot(session).control_mode == "dialog"
    assert drain_dialog(session).action == "scripted_movement"

    approach = snapshot(session).movement_cue
    assert approach is not None
    assert approach.tracks[0].actor_id == "PALLETTOWN_OAK"
    assert (
        approach.tracks[0].steps
        == {
            10: (
                Direction.NORTH,
                Direction.EAST,
                Direction.NORTH,
                Direction.EAST,
                Direction.NORTH,
            ),
            11: (
                Direction.EAST,
                Direction.NORTH,
                Direction.EAST,
                Direction.NORTH,
                Direction.EAST,
                Direction.NORTH,
            ),
        }[column]
    )
    assert session.acknowledge_cue("stale") == ActionResult("blocked", "stale_movement_cue")
    assert session.acknowledge_cue(approach.id).action == "dialog_opened"
    assert session.acknowledge_cue(approach.id) == ActionResult("blocked", "stale_movement_cue")
    assert drain_dialog(session).action == "scripted_movement"

    if column == 11:
        oak_adjustment = snapshot(session).movement_cue
        assert oak_adjustment is not None
        assert [track.actor_id for track in oak_adjustment.tracks] == ["PALLETTOWN_OAK"]
        assert session.acknowledge_cue(oak_adjustment.id).action == "scripted_movement"
        player_adjustment = snapshot(session).movement_cue
        assert player_adjustment is not None
        assert [track.actor_id for track in player_adjustment.tracks] == ["player"]
        assert session.acknowledge_cue(player_adjustment.id).action == "scripted_movement"
    escort = snapshot(session).movement_cue
    assert escort is not None
    assert [track.actor_id for track in escort.tracks] == ["player", "PALLETTOWN_OAK"]
    player_escort, oak_escort = escort.tracks
    assert player_escort.start == Position(x=10, y=1)
    assert player_escort.steps == (
        (Direction.SOUTH,) * 6
        + (Direction.WEST,)
        + (Direction.SOUTH,) * 5
        + (Direction.EAST,) * 3
        + (Direction.NORTH,)
    )
    assert len(player_escort.steps) == 16
    assert player_escort.end == Position(x=12, y=11)
    player_positions: list[Position] = []
    position = player_escort.start
    for direction in player_escort.steps:
        position = position.moved(direction)
        player_positions.append(position)
        assert world.maps["PALLET_TOWN"].contains(position)
    assert player_positions[14] == Position(x=12, y=12)
    assert player_positions[15] == Position(x=12, y=11)
    assert Position(x=12, y=10) not in player_positions

    assert oak_escort.start == Position(x=10, y=2)
    assert oak_escort.steps == (
        (Direction.SOUTH,) * 5
        + (Direction.WEST,)
        + (Direction.SOUTH,) * 5
        + (Direction.EAST,) * 3
        + (Direction.NORTH,)
    )
    assert oak_escort.end == Position(x=12, y=11)
    assert len(oak_escort.steps) == 15
    assert oak_escort.steps[-1] == Direction.NORTH
    oak_positions: list[Position] = []
    position = oak_escort.start
    for direction in oak_escort.steps:
        position = position.moved(direction)
        oak_positions.append(position)
    assert (player_positions[14], oak_positions[14]) == (
        Position(x=12, y=12),
        Position(x=12, y=11),
    )
    assert (player_positions[15], oak_positions[-1]) == (
        Position(x=12, y=11),
        Position(x=12, y=11),
    )
    assert session.acknowledge_cue(escort.id).action == "transitioned"

    transition_state = snapshot(session)
    assert transition_state.map.id == "OAKS_LAB"
    assert transition_state.player.position == world.maps["OAKS_LAB"].warps[1].position
    assert transition_state.control_mode == "transition"
    assert transition_state.movement_cue is None
    assert transition_state.transition is not None
    assert session.acknowledge_transition("stale") == ActionResult("blocked", "stale_transition")
    assert (
        session.acknowledge_transition(transition_state.transition.id).action == "scripted_movement"
    )

    oak_entry = snapshot(session).movement_cue
    assert oak_entry is not None and len(oak_entry.tracks[0].steps) == 3
    assert session.acknowledge_cue(oak_entry.id).action == "scripted_movement"
    player_entry = snapshot(session).movement_cue
    assert player_entry is not None
    assert [track.actor_id for track in player_entry.tracks] == ["player"]
    assert player_entry.tracks[0].start == Position(x=5, y=11)
    assert player_entry.tracks[0].steps == (Direction.NORTH,) * 8
    assert player_entry.tracks[0].end == Position(x=5, y=3)
    assert session.acknowledge_cue(player_entry.id).action == "dialog_opened"
    drain_dialog(session)
    state = snapshot(session)
    assert state.control_mode == "free"
    assert {
        "EVENT_FOLLOWED_OAK_INTO_LAB",
        "EVENT_FOLLOWED_OAK_INTO_LAB_2",
        "EVENT_OAK_ASKED_TO_CHOOSE_MON",
    }.issubset(state.flags)
    assert not next(actor for actor in state.map.actors if actor.id == "OAKSLAB_OAK2").visible
    assert next(actor for actor in state.map.actors if actor.id == "OAKSLAB_OAK1").visible
    return session


def pallet_town_session(world: WorldDefinition, story: StoryDefinition) -> GameSession:
    session = GameSession(world, story)
    walk_to(session, world, Position(x=7, y=1))
    walk_to(session, world, Position(x=2, y=7))
    assert complete_direction(session, Direction.SOUTH).action == "transitioned"
    assert session.map_id == "PALLET_TOWN"
    return session


def source_fallback_story(world: WorldDefinition) -> StoryDefinition:
    return StoryDefinition(
        start_map=world.start_map,
        start_position=world.player_spawn,
        start_facing=Direction.SOUTH,
        event_flags=frozenset(),
        initial_actors={
            map_id: tuple(
                ActorState(
                    id=npc.id,
                    position=npc.position,
                    facing=npc.facing,
                    visible=npc.visible,
                    sprite=npc.sprite,
                )
                for npc in map_definition.npcs
            )
            for map_id, map_definition in world.maps.items()
        },
        texts={},
        movements={},
        starters={},
        nodes=(),
        provenance=world.maps[world.start_map].provenance,
    )


def face_and_interact(session: GameSession, direction: Direction) -> ActionResult:
    complete_direction(session, direction)
    return session.interact()


def test_story_source_parsers_are_strict_and_expand_rle() -> None:
    assert parse_new_game_warp(
        "NewGameWarp:\n special_warp_spec REDS_HOUSE_2F, 3, 6, REDS_HOUSE_2\n"
    ) == ("REDS_HOUSE_2F", Position(x=3, y=6))
    assert parse_rgbds_constants(
        "const_def $10\nconst FIRST\nconst_skip 2\nconst SECOND\nDEF ALIAS EQU FIRST\n"
    ) == {"FIRST": 0x10, "SECOND": 0x13, "ALIAS": 0x10}
    assert parse_movement("Walk:\n db PAD_UP, 2\n db PAD_LEFT, 1\n db -1\n", "Walk", rle=True) == (
        Direction.NORTH,
        Direction.NORTH,
        Direction.WEST,
    )
    with pytest.raises(ParseError, match="terminator"):
        parse_movement("Walk:\n db PAD_UP, 1\n", "Walk", rle=True)
    assert parse_movement_sequence(
        "First\n db NPC_MOVEMENT_DOWN\nSecond\n db NPC_MOVEMENT_RIGHT\n db -1\n",
        ("First", "Second"),
        rle=False,
    ) == (Direction.SOUTH, Direction.EAST)


def test_simulated_joypad_rle_reverses_expanded_buffer_execution_order() -> None:
    content = "Walk:\n db PAD_UP, 2\n db PAD_LEFT, 1\n db PAD_DOWN, 2\n db -1\n"

    assert parse_movement(content, "Walk", rle=True) == (
        Direction.NORTH,
        Direction.NORTH,
        Direction.WEST,
        Direction.SOUTH,
        Direction.SOUTH,
    )
    assert parse_simulated_joypad_rle(content, "Walk") == (
        Direction.SOUTH,
        Direction.SOUTH,
        Direction.WEST,
        Direction.NORTH,
        Direction.NORTH,
    )


def test_warp_interrupted_movement_includes_landing_and_discards_later_input(
    pokered_world: WorldDefinition,
    pokered_story: StoryDefinition,
) -> None:
    decoded = pokered_story.movements["player_walk_to_lab"]
    assert len(decoded) == 17

    compiled = compile_warp_interrupted_movement(
        pokered_world.maps["PALLET_TOWN"],
        Position(x=10, y=1),
        decoded,
    )

    assert compiled.steps == (
        (Direction.SOUTH,) * 6
        + (Direction.WEST,)
        + (Direction.SOUTH,) * 5
        + (Direction.EAST,) * 3
        + (Direction.NORTH,)
    )
    assert compiled.warp.position == Position(x=12, y=11)
    assert compiled.warp.target_map == "OAKS_LAB"
    assert compiled.warp.target_warp == 2


def test_warp_interrupted_movement_rejects_a_path_without_an_on_step_warp(
    pokered_world: WorldDefinition,
) -> None:
    pallet_without_warps = pokered_world.maps["PALLET_TOWN"].model_copy(update={"warps": []})

    with pytest.raises(ParseError, match="does not encounter an on-step warp"):
        compile_warp_interrupted_movement(
            pallet_without_warps,
            Position(x=10, y=1),
            (Direction.SOUTH,),
        )


def test_story_graph_is_source_provenanced_and_rejects_dangling_choice_branches(
    pokered_story: StoryDefinition,
) -> None:
    assert all(
        node.provenance.revision == pokered_story.provenance.revision
        for node in pokered_story.nodes
    )
    payload = pokered_story.model_dump(mode="python")
    choice = next(
        command
        for node in payload["nodes"]
        for command in node["commands"]
        if command["type"] == "choice"
    )
    choice["branches"]["yes"] = ("missing_story_node",)

    with pytest.raises(ValidationError, match="unknown continuations"):
        StoryDefinition.model_validate(payload)


def test_generic_story_definition_does_not_require_pallet_flags(
    pokered_story: StoryDefinition,
) -> None:
    definition = StoryDefinition(
        start_map="GENERIC_MAP",
        start_position=Position(x=0, y=0),
        start_facing=Direction.SOUTH,
        event_flags=frozenset(),
        initial_actors={"GENERIC_MAP": ()},
        texts={},
        movements={},
        starters={},
        nodes=(),
        provenance=pokered_story.provenance,
    )

    assert definition.event_flags == frozenset()


def test_house_mom_and_tv_are_source_conditional(
    pokered_world: WorldDefinition, pokered_story: StoryDefinition
) -> None:
    session = GameSession(pokered_world, pokered_story)
    walk_to(session, pokered_world, Position(x=7, y=1))
    walk_to(session, pokered_world, Position(x=5, y=5))
    assert face_and_interact(session, Direction.NORTH).action == "dialog_opened"
    assert session.dialog is not None and session.dialog.pages[0].startswith("MOM: Right.")
    drain_dialog(session)

    walk_to(session, pokered_world, Position(x=3, y=2))
    assert face_and_interact(session, Direction.NORTH).action == "dialog_opened"
    assert session.dialog is not None and "movie" in session.dialog.pages[0]
    drain_dialog(session)
    walk_to(session, pokered_world, Position(x=2, y=1))
    assert face_and_interact(session, Direction.EAST).action == "dialog_opened"
    assert session.dialog is not None and session.dialog.pages == ["Oops, wrong side."]


@pytest.mark.parametrize(
    ("position", "facing", "interaction_id", "first_page"),
    [
        (
            Position(x=3, y=7),
            Direction.SOUTH,
            "PALLETTOWN_GIRL",
            "I'm raising\nPOKéMON too!",
        ),
        (
            Position(x=11, y=15),
            Direction.NORTH,
            "PALLETTOWN_FISHER",
            "Technology is\nincredible!",
        ),
        (
            Position(x=13, y=12),
            Direction.SOUTH,
            "TEXT_PALLETTOWN_OAKSLAB_SIGN",
            "OAK POKéMON\nRESEARCH LAB",
        ),
        (
            Position(x=7, y=8),
            Direction.SOUTH,
            "TEXT_PALLETTOWN_SIGN",
            "PALLET TOWN\nShades of your\njourney await!",
        ),
        (
            Position(x=3, y=6),
            Direction.NORTH,
            "TEXT_PALLETTOWN_PLAYERSHOUSE_SIGN",
            "RED's house ",
        ),
        (
            Position(x=11, y=6),
            Direction.NORTH,
            "TEXT_PALLETTOWN_RIVALSHOUSE_SIGN",
            "BLUE's house ",
        ),
    ],
)
def test_pallet_source_fallback_dialogs_use_story_state(
    pokered_world: WorldDefinition,
    pokered_story: StoryDefinition,
    position: Position,
    facing: Direction,
    interaction_id: str,
    first_page: str,
) -> None:
    session = pallet_town_session(pokered_world, pokered_story)
    walk_to(session, pokered_world, position)

    opened = face_and_interact(session, facing)

    assert opened == ActionResult("dialog_opened")
    state = snapshot(session)
    assert state.control_mode == "dialog"
    assert state.dialog is not None
    assert state.dialog.interaction_id == interaction_id
    assert state.dialog.pages[0] == first_page
    version = session.state_version
    assert session.move(Direction.EAST, continued=False) == ActionResult("blocked", "dialog_open")
    assert session.state_version == version
    assert drain_dialog(session).action == "dialog_closed"
    assert snapshot(session).control_mode == "free"


def test_unsupported_source_fallback_does_not_mutate_story_session(
    world: WorldDefinition,
) -> None:
    person = world.maps["OUTDOOR"].npcs[0]
    unsupported = TextInteraction(
        reference=person.interaction.reference,
        status="unsupported",
        reason="fixture script is outside the supported subset",
        provenance=person.interaction.provenance,
    )
    unsupported_person = person.model_copy(update={"interaction": unsupported})
    unsupported_outdoor = world.maps["OUTDOOR"].model_copy(update={"npcs": [unsupported_person]})
    unsupported_world = world.model_copy(
        update={"maps": {**world.maps, "OUTDOOR": unsupported_outdoor}}
    )
    session = GameSession(unsupported_world, source_fallback_story(unsupported_world))
    before = snapshot(session)

    result = session.interact()

    assert result == ActionResult(
        "unsupported_interaction", "fixture script is outside the supported subset"
    )
    assert session.state_version == 0
    assert snapshot(session) == before


@pytest.mark.parametrize("column", [10, 11])
def test_oak_escort_columns_and_lab_entry(
    pokered_world: WorldDefinition, pokered_story: StoryDefinition, column: int
) -> None:
    session = canonical_lab_session(pokered_world, pokered_story, column=column)
    assert session.map_id == "OAKS_LAB"
    assert session.player.position == Position(x=5, y=3)


@pytest.mark.parametrize(
    (
        "ball",
        "player_position",
        "direction",
        "starter",
        "rival",
        "rival_start",
        "rival_steps",
    ),
    [
        (
            "OAKSLAB_CHARMANDER_POKE_BALL",
            Position(x=5, y=3),
            Direction.EAST,
            "CHARMANDER",
            "SQUIRTLE",
            Position(x=4, y=3),
            (Direction.SOUTH, Direction.EAST, Direction.EAST, Direction.EAST),
        ),
        (
            "OAKSLAB_CHARMANDER_POKE_BALL",
            Position(x=6, y=4),
            Direction.NORTH,
            "CHARMANDER",
            "SQUIRTLE",
            Position(x=4, y=3),
            (
                Direction.SOUTH,
                Direction.SOUTH,
                Direction.EAST,
                Direction.EAST,
                Direction.EAST,
                Direction.NORTH,
            ),
        ),
        (
            "OAKSLAB_SQUIRTLE_POKE_BALL",
            Position(x=7, y=4),
            Direction.NORTH,
            "SQUIRTLE",
            "BULBASAUR",
            Position(x=4, y=3),
            (
                Direction.SOUTH,
                Direction.SOUTH,
                Direction.EAST,
                Direction.EAST,
                Direction.EAST,
                Direction.EAST,
                Direction.NORTH,
            ),
        ),
        (
            "OAKSLAB_SQUIRTLE_POKE_BALL",
            Position(x=7, y=2),
            Direction.SOUTH,
            "SQUIRTLE",
            "BULBASAUR",
            Position(x=4, y=3),
            (
                Direction.SOUTH,
                Direction.EAST,
                Direction.EAST,
                Direction.EAST,
                Direction.EAST,
            ),
        ),
        (
            "OAKSLAB_BULBASAUR_POKE_BALL",
            Position(x=8, y=4),
            Direction.NORTH,
            "BULBASAUR",
            "CHARMANDER",
            Position(x=4, y=3),
            (Direction.SOUTH, Direction.EAST, Direction.EAST),
        ),
        (
            "OAKSLAB_BULBASAUR_POKE_BALL",
            Position(x=9, y=3),
            Direction.WEST,
            "BULBASAUR",
            "CHARMANDER",
            Position(x=9, y=8),
            (Direction.EAST,),
        ),
    ],
)
def test_all_starters_no_yes_counter_and_event_timing(
    pokered_world: WorldDefinition,
    pokered_story: StoryDefinition,
    ball: str,
    player_position: Position,
    direction: Direction,
    starter: str,
    rival: str,
    rival_start: Position,
    rival_steps: tuple[Direction, ...],
) -> None:
    session = canonical_lab_session(pokered_world, pokered_story)
    walk_to(session, pokered_world, player_position)
    assert face_and_interact(session, direction).action == "dialog_opened"
    drain_dialog(session)
    assert snapshot(session).choice is not None
    first_choice = snapshot(session).choice
    assert first_choice is not None
    assert session.choose("stale-choice", "confirm") == ActionResult("blocked", "stale_choice")
    assert choose(session, "cancel") == ActionResult("choice_closed", "declined")
    assert snapshot(session).has_starter is False
    assert next(actor for actor in snapshot(session).map.actors if actor.id == ball).visible

    assert session.interact().action == "dialog_opened"
    drain_dialog(session)
    second_choice = snapshot(session).choice
    assert second_choice is not None
    assert second_choice.instance_id != first_choice.instance_id
    assert session.choose(first_choice.instance_id, "confirm") == ActionResult(
        "blocked", "stale_choice"
    )
    assert choose(session, "confirm").action == "dialog_opened"
    state = snapshot(session)
    assert state.has_starter is False
    assert state.player_starter == starter
    assert state.party == []
    assert "EVENT_GOT_STARTER" not in state.flags
    assert not next(actor for actor in state.map.actors if actor.id == ball).visible

    assert drain_dialog(session).action == "scripted_movement"
    state = snapshot(session)
    assert state.has_starter is True
    assert state.party[0].name == starter
    assert state.party[0].level == 5
    cue = snapshot(session).movement_cue
    assert cue is not None
    assert len(cue.tracks) == 1
    assert cue.tracks[0].actor_id == "OAKSLAB_RIVAL"
    assert cue.tracks[0].start == rival_start
    assert cue.tracks[0].steps == rival_steps
    assert session.acknowledge_cue(cue.id).action == "dialog_opened"
    state = snapshot(session)
    assert (
        next(actor for actor in state.map.actors if actor.id == "OAKSLAB_RIVAL").facing
        == Direction.NORTH
    )
    assert state.rival_starter is None
    rival_ball = pokered_story.starters[ball].rival_ball_actor
    assert next(actor for actor in state.map.actors if actor.id == rival_ball).visible
    assert drain_current_dialog(session).action == "dialog_opened"
    state = snapshot(session)
    assert state.rival_starter == rival
    assert not next(actor for actor in state.map.actors if actor.id == rival_ball).visible
    assert "EVENT_GOT_STARTER" not in snapshot(session).flags
    assert drain_dialog(session).action == "dialog_closed"
    assert "EVENT_GOT_STARTER" in snapshot(session).flags
    assert session.interact().action == "nothing_to_interact"


def test_exit_prevention_and_prebattle_boundary(
    pokered_world: WorldDefinition, pokered_story: StoryDefinition
) -> None:
    session = canonical_lab_session(pokered_world, pokered_story)
    result = walk_to(session, pokered_world, Position(x=5, y=6))
    assert result.action == "dialog_opened"
    assert "Don't go" in "\n".join(session.dialog.pages if session.dialog else [])
    warning_state = snapshot(session)
    assert (
        next(actor for actor in warning_state.map.actors if actor.id == "OAKSLAB_OAK1").facing
        == Direction.SOUTH
    )
    assert (
        next(actor for actor in warning_state.map.actors if actor.id == "OAKSLAB_RIVAL").facing
        == Direction.SOUTH
    )
    assert drain_dialog(session).action == "scripted_movement"
    cue = snapshot(session).movement_cue
    assert cue is not None
    session.acknowledge_cue(cue.id)
    assert session.player.position == Position(x=5, y=5)

    walk_to(session, pokered_world, Position(x=5, y=3))
    assert face_and_interact(session, Direction.EAST).action == "dialog_opened"
    drain_dialog(session)
    choose(session, "confirm")
    assert drain_dialog(session).action == "scripted_movement"
    rival_cue = snapshot(session).movement_cue
    assert rival_cue is not None
    session.acknowledge_cue(rival_cue.id)
    drain_dialog(session)
    assert "EVENT_GOT_STARTER" in snapshot(session).flags

    result = walk_to(session, pokered_world, Position(x=5, y=6))
    assert result.action == "dialog_opened"
    assert (
        next(actor for actor in snapshot(session).map.actors if actor.id == "OAKSLAB_RIVAL").facing
        == Direction.SOUTH
    )
    assert drain_dialog(session).action == "scripted_movement"
    challenge_cue = snapshot(session).movement_cue
    assert challenge_cue is not None
    assert challenge_cue.tracks[0].actor_id == "OAKSLAB_RIVAL"
    assert challenge_cue.tracks[0].start == Position(x=7, y=4)
    assert challenge_cue.tracks[0].steps == (
        Direction.WEST,
        Direction.WEST,
        Direction.SOUTH,
    )
    assert session.acknowledge_cue(challenge_cue.id) == ActionResult(
        "phase_boundary", "rival_battle_deferred"
    )
    state = snapshot(session)
    assert state.control_mode == "phase_boundary"
    rival = next(actor for actor in state.map.actors if actor.id == "OAKSLAB_RIVAL")
    assert rival.position == Position(x=5, y=5)
    assert rival.facing == Direction.SOUTH
    assert "EVENT_BATTLED_RIVAL_IN_OAKS_LAB" not in state.flags
    assert session.move(Direction.NORTH, continued=False) == ActionResult(
        "blocked", "control_phase_boundary"
    )


def test_story_sessions_are_isolated(
    pokered_world: WorldDefinition, pokered_story: StoryDefinition
) -> None:
    first = GameSession(pokered_world, pokered_story)
    second = GameSession(pokered_world, pokered_story)
    walk_to(first, pokered_world, Position(x=7, y=1))
    assert first.map_id == "REDS_HOUSE_1F"
    assert second.map_id == "REDS_HOUSE_2F"
    assert snapshot(second).flags == []
