from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .common import Direction, Position, StrictModel
from .map import TileDefinition

Surface = Literal["walkable", "grass", "water", "blocked"]


class SourceProvenance(StrictModel):
    repository: str
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    files: dict[str, str]


class ImportedWarp(StrictModel):
    index: int = Field(gt=0)
    position: Position
    target_map_constant: str
    target_warp: int = Field(gt=0)


class ImportedObject(StrictModel):
    source_id: str
    position: Position
    sprite: str
    movement: str
    facing: str
    text_reference: str


class ImportedMap(StrictModel):
    id: str
    source_name: str
    source_constant: str
    tileset: str
    block_width: int = Field(gt=0)
    block_height: int = Field(gt=0)
    source_blocks: list[list[int]]
    source_tile_ids: list[list[int]]
    surfaces: list[list[Surface]]
    warps: list[ImportedWarp]
    objects: list[ImportedObject]

    @model_validator(mode="after")
    def validate_dimensions(self) -> ImportedMap:
        logical_width = self.block_width * 2
        logical_height = self.block_height * 2
        if len(self.source_blocks) != self.block_height or any(
            len(row) != self.block_width for row in self.source_blocks
        ):
            raise ValueError("source block dimensions do not match the declared map dimensions")
        for label, rows in (("source_tile_ids", self.source_tile_ids), ("surfaces", self.surfaces)):
            if len(rows) != logical_height or any(len(row) != logical_width for row in rows):
                raise ValueError(f"{label} dimensions must be {logical_width}x{logical_height}")
        indices = [warp.index for warp in self.warps]
        if indices != list(range(1, len(indices) + 1)):
            raise ValueError("source warp indices must be unique and sequential from 1")
        return self


class ImportedBundle(StrictModel):
    source: SourceProvenance
    maps: list[ImportedMap]


class VisualOverride(StrictModel):
    position: Position
    tile: str


class NPCOverlay(StrictModel):
    source_object: str
    id: str
    name: str
    facing: Direction | None = Field(default=None, strict=False)
    dialog: list[str] = Field(min_length=1)
    appearance: str


class TransitionOverlay(StrictModel):
    source_position: Position
    last_map_context: str | None = None
    target_facing: Direction = Field(strict=False)


class MapOverlay(StrictModel):
    id: str
    name: str
    source_map: str
    player_spawn: Position | None = None
    terrain_tiles: dict[Surface, str]
    visual_overrides: list[VisualOverride] = Field(default_factory=list)
    npcs: list[NPCOverlay] = Field(default_factory=list)
    transitions: list[TransitionOverlay] = Field(default_factory=list)


class WorldOverlay(StrictModel):
    start_map: str
    player_appearance: str
    tile_definitions: list[TileDefinition]
    maps: list[MapOverlay]
