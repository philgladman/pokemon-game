from backend.app.engine.game import GameSession
from backend.app.models.common import Direction, Position
from backend.app.models.map import WorldDefinition


def test_player_moves_one_authoritative_tile(world: WorldDefinition) -> None:
    session = GameSession(world)

    result = session.move(Direction.SOUTH)

    assert result.action == "moved"
    assert session.player.position.model_dump() == {"x": 5, "y": 8}
    assert session.state_version == 1


def test_blocked_terrain_changes_facing_but_not_position(world: WorldDefinition) -> None:
    session = GameSession(world)
    session.move(Direction.NORTH)
    session.move(Direction.WEST)

    result = session.move(Direction.NORTH)

    assert result.action == "turned"
    assert result.reason == "terrain"
    assert session.player.position.model_dump() == {"x": 4, "y": 6}
    assert session.player.facing == Direction.NORTH


def test_repeated_block_does_not_change_state_version(world: WorldDefinition) -> None:
    session = GameSession(world)
    session.move(Direction.NORTH)
    session.move(Direction.WEST)
    session.move(Direction.NORTH)
    version_after_turn = session.state_version

    result = session.move(Direction.NORTH)

    assert result.action == "blocked"
    assert result.reason == "terrain"
    assert session.state_version == version_after_turn


def test_map_boundaries_are_blocked(world: WorldDefinition) -> None:
    pallet_town = world.maps["pallet_town"]

    assert GameSession._blocked_reason(pallet_town, Position(x=-1, y=0)) == "map_boundary"
    assert GameSession._blocked_reason(pallet_town, Position(x=20, y=17)) == "map_boundary"


def test_npc_collision_and_direct_front_interaction(world: WorldDefinition) -> None:
    session = GameSession(world)
    session.move(Direction.SOUTH)
    session.move(Direction.WEST)

    collision = session.move(Direction.WEST)
    opened = session.interact()

    assert collision.reason == "npc"
    assert opened.action == "dialog_opened"
    assert session.dialog is not None
    assert session.dialog.npc_id == "town_gardener"
    assert session.dialog.line_index == 0


def test_server_owns_dialog_progression(world: WorldDefinition) -> None:
    session = GameSession(world)
    session.move(Direction.SOUTH)
    session.move(Direction.WEST)
    session.move(Direction.WEST)
    session.interact()

    blocked = session.move(Direction.NORTH)
    advanced = session.interact()
    closed = session.interact()

    assert blocked.reason == "dialog_open"
    assert advanced.action == "dialog_advanced"
    assert closed.action == "dialog_closed"
    assert session.dialog is None


def test_building_transition_is_atomic(world: WorldDefinition) -> None:
    session = GameSession(world)
    session.move(Direction.NORTH)
    result = session.move(Direction.NORTH)

    assert result.action == "transitioned"
    assert session.map_id == "reds_house_1f"
    assert session.player.position.model_dump() == {"x": 2, "y": 7}
    assert session.player.facing == Direction.NORTH

    session.move(Direction.NORTH)
    exit_result = session.move(Direction.SOUTH)
    assert exit_result.action == "transitioned"
    assert session.map_id == "pallet_town"
    assert session.player.position.model_dump() == {"x": 5, "y": 5}
