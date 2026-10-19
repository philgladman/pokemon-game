import pytest

from backend.app.engine.game import ActionResult, GameSession
from backend.app.models.common import Direction, Position
from backend.app.models.map import WorldDefinition


def complete_direction(session: GameSession, direction: Direction) -> ActionResult:
    result = session.move(direction, continued=False)
    if result.action == "turned":
        result = session.move(direction, continued=True)
    return result


@pytest.mark.parametrize(
    ("last_stop", "changed"),
    [
        (last_stop, changed)
        for last_stop in Direction
        for changed in Direction
        if changed != last_stop
    ],
)
def test_every_changed_direction_after_neutral_is_turn_only(
    world: WorldDefinition,
    last_stop: Direction,
    changed: Direction,
) -> None:
    session = GameSession(world)
    session.move(last_stop, continued=False)
    position = session.player.position
    version = session.state_version

    result = session.move(changed, continued=False)

    assert result == ActionResult("turned", "direction_change")
    assert session.player.position == position
    assert session.player.facing == changed
    assert session.state_version == version + 1


def test_same_direction_after_neutral_moves_and_leaves_turn_check_armed(
    world: WorldDefinition,
) -> None:
    session = GameSession(world)
    assert session.move(Direction.WEST, continued=False).action == "turned"

    moved = session.move(Direction.WEST, continued=False)
    changed = session.move(Direction.NORTH, continued=True)

    assert moved.action == "moved"
    assert session.player.position == Position(x=0, y=1)
    assert changed == ActionResult("turned", "direction_change")
    assert session.player.facing == Direction.NORTH


def test_held_direction_moves_on_the_continued_sample_after_turn(
    world: WorldDefinition,
) -> None:
    session = GameSession(world)

    turned = session.move(Direction.WEST, continued=False)
    moved = session.move(Direction.WEST, continued=True)

    assert turned.action == "turned"
    assert moved.action == "moved"
    assert session.player.position == Position(x=0, y=1)


def test_direction_change_moves_after_turn_check_was_consumed(world: WorldDefinition) -> None:
    session = GameSession(world)
    session.move(Direction.WEST, continued=False)

    result = session.move(Direction.EAST, continued=True)

    assert result.action == "transitioned"
    assert session.map_id == "INDOOR"


def test_blocked_terrain_does_not_change_state_after_facing_turn(world: WorldDefinition) -> None:
    session = GameSession(world)
    session.move(Direction.NORTH, continued=False)
    version_after_turn = session.state_version

    result = session.move(Direction.NORTH, continued=True)

    assert result == ActionResult("blocked", "terrain")
    assert session.player.position == Position(x=1, y=1)
    assert session.state_version == version_after_turn


def test_npc_collision_and_source_interaction(world: WorldDefinition) -> None:
    session = GameSession(world)

    collision = session.move(Direction.SOUTH, continued=False)
    opened = session.interact()

    assert collision.reason == "npc"
    assert opened.action == "dialog_opened"
    assert session.dialog is not None
    assert session.dialog.interaction_id == "PERSON"
    assert session.dialog.pages[0] == "Source page one"


def test_dialog_open_and_close_reset_input_continuity(world: WorldDefinition) -> None:
    session = GameSession(world)
    session.move(Direction.SOUTH, continued=False)
    session.interact()

    assert session.move(Direction.NORTH, continued=True).reason == "dialog_open"
    assert session.interact().action == "dialog_advanced"
    assert session.interact().action == "dialog_closed"

    result = session.move(Direction.NORTH, continued=True)
    assert result.action == "turned"
    assert result.reason == "direction_change"


def test_transition_is_atomic_and_resets_input_continuity(world: WorldDefinition) -> None:
    session = GameSession(world)
    assert complete_direction(session, Direction.EAST).action == "transitioned"
    assert session.map_id == "INDOOR"
    assert session.player.position == Position(x=1, y=3)

    result = session.move(Direction.WEST, continued=True)

    assert result.action == "turned"
    assert session.player.position == Position(x=1, y=3)


def test_last_map_warp_returns_to_source_warp(world: WorldDefinition) -> None:
    session = GameSession(world)
    complete_direction(session, Direction.EAST)

    result = complete_direction(session, Direction.SOUTH)

    assert result.action == "transitioned"
    assert session.map_id == "OUTDOOR"
    assert session.player.position == Position(x=2, y=2)
    assert session.player.facing == Direction.SOUTH

    assert complete_direction(session, Direction.NORTH).action == "transitioned"
    assert session.map_id == "INDOOR"


def test_edge_exit_only_triggers_outward_from_its_tile(world: WorldDefinition) -> None:
    session = GameSession(world)
    complete_direction(session, Direction.EAST)

    result = complete_direction(session, Direction.WEST)

    assert result.action == "moved"
    assert session.map_id == "INDOOR"
    assert session.player.position == Position(x=0, y=3)


def test_map_boundaries_are_blocked(world: WorldDefinition) -> None:
    outdoor = world.maps["OUTDOOR"]

    assert GameSession._blocked_reason(outdoor, Position(x=-1, y=0)) == "map_boundary"
