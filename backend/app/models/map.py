from __future__ import annotations

from pydantic import Field, model_validator

from .assets import AppearanceDefinition
from .common import Direction, Position, StrictModel


class TileDefinition(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    walkable: bool
    surfable: bool = False
    appearance: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$")

    @model_validator(mode="after")
    def water_is_not_walkable(self) -> TileDefinition:
        if self.walkable and self.surfable:
            raise ValueError("a tile cannot be both walkable and surfable")
        return self


class NPCDefinition(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1)
    position: Position
    facing: Direction = Field(strict=False)
    dialog: list[str] = Field(min_length=1)
    appearance: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$")


class TransitionDefinition(StrictModel):
    position: Position
    target_map: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    target_position: Position
    target_facing: Direction = Field(strict=False)


class SourceReference(StrictModel):
    repository: str
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    map_name: str


class MapDefinition(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    tiles: list[list[str]]
    tile_definitions: dict[str, TileDefinition]
    player_spawn: Position | None = None
    npcs: list[NPCDefinition] = Field(default_factory=list)
    transitions: list[TransitionDefinition] = Field(default_factory=list)
    source: SourceReference

    def contains(self, position: Position) -> bool:
        return 0 <= position.x < self.width and 0 <= position.y < self.height

    def tile_at(self, position: Position) -> TileDefinition:
        return self.tile_definitions[self.tiles[position.y][position.x]]

    def npc_at(self, position: Position) -> NPCDefinition | None:
        return next((npc for npc in self.npcs if npc.position == position), None)

    def transition_at(self, position: Position) -> TransitionDefinition | None:
        return next(
            (transition for transition in self.transitions if transition.position == position),
            None,
        )

    @model_validator(mode="after")
    def validate_layout(self) -> MapDefinition:
        for tile_id, tile_definition in self.tile_definitions.items():
            if tile_id != tile_definition.id:
                raise ValueError(
                    f"tile definition key {tile_id!r} does not match id "
                    f"{tile_definition.id!r} in map {self.id!r}"
                )

        if len(self.tiles) != self.height:
            raise ValueError(f"tiles must contain exactly {self.height} rows")
        for row_number, row in enumerate(self.tiles):
            if len(row) != self.width:
                raise ValueError(f"tile row {row_number} must contain exactly {self.width} entries")
            unknown = set(row) - self.tile_definitions.keys()
            if unknown:
                raise ValueError(
                    f"tile row {row_number} references unknown tiles: {sorted(unknown)}"
                )

        occupied: dict[tuple[int, int], NPCDefinition] = {}
        for npc in self.npcs:
            self._validate_position(npc.position, f"NPC {npc.id}")
            key = (npc.position.x, npc.position.y)
            if key in occupied:
                raise ValueError(f"multiple NPCs occupy {key}")
            occupied[key] = npc
            if self.tile_at(npc.position).walkable is False:
                raise ValueError(f"NPC {npc.id} must be placed on a walkable tile")

        transition_positions: set[tuple[int, int]] = set()
        for transition in self.transitions:
            self._validate_position(transition.position, "transition")
            key = (transition.position.x, transition.position.y)
            if key in transition_positions:
                raise ValueError(f"multiple transitions occupy {key}")
            transition_positions.add(key)
            overlapping_npc = occupied.get(key)
            if overlapping_npc is not None:
                raise ValueError(
                    f"transition at {key} overlaps NPC {overlapping_npc.id!r} and is unreachable"
                )
            if self.tile_at(transition.position).walkable is False:
                raise ValueError(f"transition at {key} must be on a walkable tile")

        if self.player_spawn is not None:
            self._validate_position(self.player_spawn, "player spawn")
            if self.tile_at(self.player_spawn).walkable is False:
                raise ValueError("player spawn must be on a walkable tile")
            if self.npc_at(self.player_spawn) is not None:
                raise ValueError("player spawn cannot overlap an NPC")
        return self

    def _validate_position(self, position: Position, label: str) -> None:
        if not self.contains(position):
            raise ValueError(f"{label} position {position} is outside map bounds")


class WorldDefinition(StrictModel):
    start_map: str
    player_appearance: str
    asset_manifest: dict[str, AppearanceDefinition]
    maps: dict[str, MapDefinition]

    @model_validator(mode="after")
    def validate_cross_references(self) -> WorldDefinition:
        for appearance_id, appearance in self.asset_manifest.items():
            if appearance_id != appearance.id:
                raise ValueError(
                    f"asset manifest key {appearance_id!r} does not match id {appearance.id!r}"
                )
        for map_id, map_definition in self.maps.items():
            if map_id != map_definition.id:
                raise ValueError(f"map key {map_id!r} does not match id {map_definition.id!r}")

        if self.start_map not in self.maps:
            raise ValueError(f"start map {self.start_map!r} does not exist")
        start = self.maps[self.start_map]
        if start.player_spawn is None:
            raise ValueError("start map must define a player spawn")
        if self.player_appearance not in self.asset_manifest:
            raise ValueError(f"unknown player appearance {self.player_appearance!r}")

        for map_id, map_definition in self.maps.items():
            for tile in map_definition.tile_definitions.values():
                if tile.appearance not in self.asset_manifest:
                    raise ValueError(f"tile {tile.id} uses unknown appearance {tile.appearance!r}")
            for npc in map_definition.npcs:
                if npc.appearance not in self.asset_manifest:
                    raise ValueError(f"NPC {npc.id} uses unknown appearance {npc.appearance!r}")
            for transition in map_definition.transitions:
                target = self.maps.get(transition.target_map)
                if target is None:
                    raise ValueError(
                        f"transition from {map_id} targets unknown map {transition.target_map}"
                    )
                if not target.contains(transition.target_position):
                    raise ValueError(
                        f"transition from {map_id} targets an out-of-bounds position in {target.id}"
                    )
                if not target.tile_at(transition.target_position).walkable:
                    raise ValueError(
                        f"transition from {map_id} targets a blocked tile in {target.id}"
                    )
                if target.npc_at(transition.target_position) is not None:
                    raise ValueError(f"transition from {map_id} targets an NPC in {target.id}")
        return self
