from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .common import Direction, Position, StrictModel


class SourceProvenance(StrictModel):
    repository: str
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    file: str
    symbol: str | None = None


class TextInteraction(StrictModel):
    reference: str
    status: Literal["direct", "unsupported"]
    template_pages: list[str] = Field(default_factory=list)
    reason: str | None = None
    provenance: SourceProvenance

    @model_validator(mode="after")
    def validate_resolution(self) -> TextInteraction:
        if self.status == "direct" and not self.template_pages:
            raise ValueError("direct text interactions require at least one page")
        if self.status == "unsupported" and not self.reason:
            raise ValueError("unsupported text interactions require a reason")
        return self


class NPCDefinition(StrictModel):
    id: str
    object_index: int = Field(gt=0)
    position: Position
    facing: Direction = Field(strict=False)
    movement: str
    visible: bool = True
    sprite: str
    interaction: TextInteraction
    provenance: SourceProvenance


class BackgroundEvent(StrictModel):
    position: Position
    interaction: TextInteraction
    provenance: SourceProvenance


class WarpDefinition(StrictModel):
    index: int = Field(gt=0)
    position: Position
    target_map: str
    target_warp: int = Field(gt=0)
    uses_last_map: bool = False
    trigger: Literal["on_step", "edge_exit"] = "on_step"
    outward: Direction | None = Field(default=None, strict=False)
    provenance: SourceProvenance

    @model_validator(mode="after")
    def validate_trigger(self) -> WarpDefinition:
        if self.trigger == "edge_exit" and self.outward is None:
            raise ValueError("edge-exit warps require an outward direction")
        if self.trigger == "on_step" and self.outward is not None:
            raise ValueError("on-step warps cannot define an outward direction")
        return self


class MapConnection(StrictModel):
    direction: Direction = Field(strict=False)
    target_map: str
    offset: int
    available: bool
    provenance: SourceProvenance


class MapDefinition(StrictModel):
    id: str
    source_name: str
    kind: Literal["outdoor", "indoor"]
    last_map_target: str | None = None
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    walkable: list[list[bool]]
    player_spawn: Position | None = None
    npcs: list[NPCDefinition] = Field(default_factory=list)
    background_events: list[BackgroundEvent] = Field(default_factory=list)
    warps: list[WarpDefinition] = Field(default_factory=list)
    connections: list[MapConnection] = Field(default_factory=list)
    provenance: SourceProvenance

    def contains(self, position: Position) -> bool:
        return 0 <= position.x < self.width and 0 <= position.y < self.height

    def is_walkable(self, position: Position) -> bool:
        return self.walkable[position.y][position.x]

    def npc_at(self, position: Position) -> NPCDefinition | None:
        return next(
            (npc for npc in self.npcs if npc.visible and npc.position == position),
            None,
        )

    def background_event_at(self, position: Position) -> BackgroundEvent | None:
        return next((event for event in self.background_events if event.position == position), None)

    def warp_at(
        self,
        position: Position,
        trigger: Literal["on_step", "edge_exit"] | None = None,
    ) -> WarpDefinition | None:
        return next(
            (
                warp
                for warp in self.warps
                if warp.position == position and (trigger is None or warp.trigger == trigger)
            ),
            None,
        )

    def edge_exit_at(
        self,
        position: Position,
        direction: Direction,
    ) -> WarpDefinition | None:
        warp = self.warp_at(position, "edge_exit")
        return warp if warp is not None and warp.outward == direction else None

    @model_validator(mode="after")
    def validate_layout(self) -> MapDefinition:
        self._validate_rows(self.walkable, self.height, self.width, "walkable")
        if self.kind == "outdoor" and self.last_map_target is not None:
            raise ValueError("outdoor maps cannot define a LAST_MAP target")
        if self.kind == "indoor" and self.last_map_target is None:
            raise ValueError("indoor maps require their canonical LAST_MAP target")
        occupied: set[tuple[int, int]] = set()
        for npc in self.npcs:
            self._validate_position(npc.position, f"NPC {npc.id}")
            key = (npc.position.x, npc.position.y)
            if npc.visible and key in occupied:
                raise ValueError(f"multiple visible NPCs occupy {key}")
            if npc.visible:
                occupied.add(key)
        for event in self.background_events:
            self._validate_position(event.position, "background event")
        for expected, warp in enumerate(self.warps, start=1):
            if warp.index != expected:
                raise ValueError("warp indices must be sequential from 1")
            self._validate_position(warp.position, f"warp {warp.index}")
            if warp.trigger == "edge_exit" and not self._is_outward_boundary(
                warp.position, warp.outward
            ):
                raise ValueError(
                    f"edge-exit warp {warp.index} is not on its {warp.outward} boundary"
                )
        if self.player_spawn is not None:
            self._validate_position(self.player_spawn, "player spawn")
            if not self.is_walkable(self.player_spawn):
                raise ValueError("player spawn must be on a passable source tile")
        return self

    @staticmethod
    def _validate_rows(rows: list[list[bool]], height: int, width: int, label: str) -> None:
        if len(rows) != height or any(len(row) != width for row in rows):
            raise ValueError(f"{label} dimensions must be {width}x{height}")

    def _validate_position(self, position: Position, label: str) -> None:
        if not self.contains(position):
            raise ValueError(f"{label} position {position} is outside map bounds")

    def _is_outward_boundary(
        self,
        position: Position,
        direction: Direction | None,
    ) -> bool:
        return {
            Direction.NORTH: position.y == 0,
            Direction.SOUTH: position.y == self.height - 1,
            Direction.WEST: position.x == 0,
            Direction.EAST: position.x == self.width - 1,
            None: False,
        }[direction]


class WorldDefinition(StrictModel):
    start_map: str
    player_spawn: Position
    player_sprite: str
    text_variables: dict[str, str]
    source_repository: str
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    maps: dict[str, MapDefinition]

    @model_validator(mode="after")
    def validate_cross_references(self) -> WorldDefinition:
        if self.start_map not in self.maps:
            raise ValueError(f"start map {self.start_map!r} does not exist")
        start = self.maps[self.start_map]
        if not start.contains(self.player_spawn) or not start.is_walkable(self.player_spawn):
            raise ValueError("world player spawn must be passable and within the start map")
        for map_id, map_definition in self.maps.items():
            if map_id != map_definition.id:
                raise ValueError(f"map key {map_id!r} does not match id {map_definition.id!r}")
            if (
                map_definition.last_map_target is not None
                and map_definition.last_map_target not in self.maps
            ):
                raise ValueError(
                    f"map {map_id} has unavailable LAST_MAP target {map_definition.last_map_target}"
                )
            for warp in map_definition.warps:
                if warp.uses_last_map and map_definition.last_map_target is None:
                    raise ValueError(
                        f"warp {warp.index} in {map_id} uses LAST_MAP without canonical metadata"
                    )
                if not warp.uses_last_map and warp.target_map not in self.maps:
                    raise ValueError(
                        f"warp {warp.index} in {map_id} targets unavailable map {warp.target_map}"
                    )
                target_map_id = (
                    map_definition.last_map_target if warp.uses_last_map else warp.target_map
                )
                if target_map_id is None or target_map_id not in self.maps:
                    continue
                target_map = self.maps[target_map_id]
                target_warp = next(
                    (
                        candidate
                        for candidate in target_map.warps
                        if candidate.index == warp.target_warp
                    ),
                    None,
                )
                if target_warp is None:
                    raise ValueError(
                        f"warp {warp.index} in {map_id} targets missing warp "
                        f"{warp.target_warp} in {target_map_id}"
                    )
                if warp.trigger == "edge_exit":
                    assert warp.outward is not None
                    landing = target_warp.position.moved(warp.outward)
                    problem: str | None = None
                    if not target_map.contains(landing):
                        problem = "outside map bounds"
                    elif not target_map.is_walkable(landing):
                        problem = "blocked terrain"
                    else:
                        npc = target_map.npc_at(landing)
                        if npc is not None:
                            problem = f"occupied by NPC {npc.id}"
                    if problem is not None:
                        raise ValueError(
                            f"edge-exit warp {warp.index} in {map_id} has invalid "
                            f"automatic landing {landing} in {target_map_id}: {problem}"
                        )
        return self
