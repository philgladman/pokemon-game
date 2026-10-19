import pytest
from pydantic import ValidationError

from backend.app.models.common import Direction, Position
from backend.app.models.map import (
    NPCDefinition,
    TextInteraction,
    WarpDefinition,
    WorldDefinition,
)
from tests.conftest import SOURCE, make_map


def test_map_rejects_malformed_walkable_dimensions() -> None:
    with pytest.raises(ValidationError, match="walkable dimensions must be 4x4"):
        make_map("ROOM", walkable=[[True]])


def test_map_rejects_out_of_bounds_npc(world: object) -> None:
    del world
    direct = TextInteraction(
        reference="TEXT",
        status="direct",
        template_pages=["hello"],
        provenance=SOURCE,
    )
    npc = NPCDefinition.model_validate(
        {
            "id": "PERSON",
            "object_index": 1,
            "position": {"x": 8, "y": 8},
            "facing": "south",
            "movement": "STAY",
            "sprite": "SPRITE_PERSON",
            "interaction": direct,
            "provenance": SOURCE,
        }
    )
    with pytest.raises(ValidationError, match="outside map bounds"):
        make_map("ROOM", npcs=[npc])


def test_direct_text_requires_pages() -> None:
    with pytest.raises(ValidationError, match="require at least one page"):
        TextInteraction(
            reference="TEXT",
            status="direct",
            provenance=SOURCE,
        )


def test_unsupported_text_requires_reason() -> None:
    with pytest.raises(ValidationError, match="require a reason"):
        TextInteraction(
            reference="TEXT",
            status="unsupported",
            provenance=SOURCE,
        )


def test_strict_position_rejects_string_coercion() -> None:
    with pytest.raises(ValidationError, match="valid integer"):
        Position.model_validate({"x": "1", "y": 0})


def test_edge_exit_requires_an_outward_direction() -> None:
    with pytest.raises(ValidationError, match="require an outward direction"):
        WarpDefinition(
            index=1,
            position=Position(x=1, y=3),
            target_map="LAST_MAP",
            target_warp=1,
            uses_last_map=True,
            trigger="edge_exit",
            provenance=SOURCE,
        )


def test_on_step_warp_rejects_an_outward_direction() -> None:
    with pytest.raises(ValidationError, match="cannot define an outward direction"):
        WarpDefinition(
            index=1,
            position=Position(x=1, y=1),
            target_map="ROOM",
            target_warp=1,
            outward=Direction.SOUTH,
            provenance=SOURCE,
        )


def test_map_rejects_edge_exit_on_the_wrong_boundary() -> None:
    warp = WarpDefinition(
        index=1,
        position=Position(x=1, y=0),
        target_map="LAST_MAP",
        target_warp=1,
        uses_last_map=True,
        trigger="edge_exit",
        outward=Direction.SOUTH,
        provenance=SOURCE,
    )
    with pytest.raises(ValidationError, match="not on its south boundary"):
        make_map("ROOM", warps=[warp], kind="indoor", last_map_target="OUTSIDE")


def make_edge_exit_world(
    target_warp_position: Position,
    *,
    target_walkable: list[list[bool]] | None = None,
    target_npcs: list[NPCDefinition] | None = None,
) -> WorldDefinition:
    edge_exit = WarpDefinition(
        index=1,
        position=Position(x=1, y=3),
        target_map="LAST_MAP",
        target_warp=1,
        uses_last_map=True,
        trigger="edge_exit",
        outward=Direction.SOUTH,
        provenance=SOURCE,
    )
    return_warp = WarpDefinition(
        index=1,
        position=target_warp_position,
        target_map="SOURCE",
        target_warp=1,
        provenance=SOURCE,
    )
    source = make_map(
        "SOURCE",
        warps=[edge_exit],
        kind="indoor",
        last_map_target="TARGET",
    )
    target = make_map(
        "TARGET",
        walkable=target_walkable,
        npcs=target_npcs,
        warps=[return_warp],
    )
    return WorldDefinition(
        start_map="TARGET",
        player_spawn=Position(x=0, y=0),
        player_sprite="SPRITE_RED",
        text_variables={},
        source_repository=SOURCE.repository,
        source_revision=SOURCE.revision,
        maps={"SOURCE": source, "TARGET": target},
    )


def test_world_rejects_edge_exit_landing_out_of_bounds() -> None:
    with pytest.raises(
        ValidationError,
        match=(
            r"edge-exit warp 1 in SOURCE has invalid automatic landing x=1 y=4 "
            r"in TARGET: outside map bounds"
        ),
    ):
        make_edge_exit_world(Position(x=1, y=3))


def test_world_rejects_edge_exit_landing_on_blocked_terrain() -> None:
    walkable = [[True] * 4 for _ in range(4)]
    walkable[2][1] = False
    with pytest.raises(
        ValidationError,
        match=(
            r"edge-exit warp 1 in SOURCE has invalid automatic landing x=1 y=2 "
            r"in TARGET: blocked terrain"
        ),
    ):
        make_edge_exit_world(Position(x=1, y=1), target_walkable=walkable)


def test_world_rejects_edge_exit_landing_on_an_npc() -> None:
    interaction = TextInteraction(
        reference="TEXT",
        status="direct",
        template_pages=["hello"],
        provenance=SOURCE,
    )
    npc = NPCDefinition(
        id="PERSON",
        object_index=1,
        position=Position(x=1, y=2),
        facing=Direction.NORTH,
        movement="STAY",
        sprite="SPRITE_PERSON",
        interaction=interaction,
        provenance=SOURCE,
    )
    with pytest.raises(
        ValidationError,
        match=(
            r"edge-exit warp 1 in SOURCE has invalid automatic landing x=1 y=2 "
            r"in TARGET: occupied by NPC PERSON"
        ),
    ):
        make_edge_exit_world(Position(x=1, y=1), target_npcs=[npc])


def test_world_accepts_a_clear_edge_exit_automatic_landing() -> None:
    world = make_edge_exit_world(Position(x=1, y=1))

    assert world.maps["TARGET"].is_walkable(Position(x=1, y=2))
