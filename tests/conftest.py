from pathlib import Path
from typing import Literal

import pytest

from backend.app.models.common import Direction, Position
from backend.app.models.map import (
    MapConnection,
    MapDefinition,
    NPCDefinition,
    SourceProvenance,
    TextInteraction,
    WarpDefinition,
    WorldDefinition,
)
from backend.app.models.story import StoryDefinition
from backend.app.source.pokered import PokeredSource

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE = SourceProvenance(
    repository="https://example.invalid/fixture",
    revision="a" * 40,
    file="fixture.asm",
    symbol="Fixture",
)


def make_map(
    map_id: str,
    *,
    walkable: list[list[bool]] | None = None,
    npcs: list[NPCDefinition] | None = None,
    warps: list[WarpDefinition] | None = None,
    kind: Literal["outdoor", "indoor"] = "outdoor",
    last_map_target: str | None = None,
) -> MapDefinition:
    return MapDefinition(
        id=map_id,
        source_name=map_id.title(),
        kind=kind,
        last_map_target=last_map_target,
        width=4,
        height=4,
        walkable=walkable or [[True] * 4 for _ in range(4)],
        npcs=npcs or [],
        warps=warps or [],
        provenance=SOURCE,
    )


@pytest.fixture(scope="session")
def world() -> WorldDefinition:
    direct = TextInteraction(
        reference="TEXT_PERSON",
        status="direct",
        template_pages=["Source page one", "Source page two"],
        provenance=SOURCE,
    )
    npc = NPCDefinition(
        id="PERSON",
        object_index=1,
        position=Position(x=1, y=2),
        facing=Direction.NORTH,
        movement="STAY",
        sprite="SPRITE_PERSON",
        interaction=direct,
        provenance=SOURCE,
    )
    outdoor_warp = WarpDefinition(
        index=1,
        position=Position(x=2, y=1),
        target_map="INDOOR",
        target_warp=1,
        provenance=SOURCE,
    )
    indoor_warp = WarpDefinition(
        index=1,
        position=Position(x=1, y=3),
        target_map="LAST_MAP",
        target_warp=1,
        uses_last_map=True,
        trigger="edge_exit",
        outward=Direction.SOUTH,
        provenance=SOURCE,
    )
    walkable = [[True] * 4 for _ in range(4)]
    walkable[0][1] = False
    outdoor = make_map("OUTDOOR", walkable=walkable, npcs=[npc], warps=[outdoor_warp])
    outdoor = outdoor.model_copy(
        update={
            "connections": [
                MapConnection(
                    direction=Direction.NORTH,
                    target_map="UNAVAILABLE",
                    offset=0,
                    available=False,
                    provenance=SOURCE,
                )
            ]
        }
    )
    indoor = make_map(
        "INDOOR",
        warps=[indoor_warp],
        kind="indoor",
        last_map_target="OUTDOOR",
    )
    return WorldDefinition(
        start_map="OUTDOOR",
        player_spawn=Position(x=1, y=1),
        player_sprite="SPRITE_RED",
        text_variables={"PLAYER": "RED", "RIVAL": "BLUE"},
        source_repository=SOURCE.repository,
        source_revision=SOURCE.revision,
        maps={"OUTDOOR": outdoor, "INDOOR": indoor},
    )


@pytest.fixture(scope="session")
def pokered_world() -> WorldDefinition:
    source_root = PROJECT_ROOT / "external/pokered"
    if not (source_root / ".git").exists():
        pytest.skip("pret/pokered checkout is not available")
    return PokeredSource(source_root).build_world()


@pytest.fixture(scope="session")
def pokered_story(pokered_world: WorldDefinition) -> StoryDefinition:
    del pokered_world
    return PokeredSource(PROJECT_ROOT / "external/pokered").build_story()
