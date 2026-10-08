from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from backend.app.models.assets import AssetManifest
from backend.app.models.common import Direction, Position
from backend.app.models.map import (
    MapDefinition,
    NPCDefinition,
    SourceReference,
    TileDefinition,
    TransitionDefinition,
    WorldDefinition,
)
from backend.app.models.source import (
    ImportedBundle,
    ImportedMap,
    ImportedWarp,
    MapOverlay,
    TransitionOverlay,
    WorldOverlay,
)
from tools.yaml_loader import load_yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IMPORTED = PROJECT_ROOT / "data" / "yaml" / "imported" / "pallet_town.yaml"
DEFAULT_OVERLAY = PROJECT_ROOT / "data" / "yaml" / "world.yaml"
DEFAULT_ASSETS = PROJECT_ROOT / "data" / "yaml" / "assets.yaml"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "generated" / "json" / "world.json"


class CompileError(RuntimeError):
    pass


def _load_yaml(path: Path) -> object:
    try:
        return load_yaml(path)
    except RuntimeError as error:
        raise CompileError(str(error)) from error


def compile_world(
    imported_path: Path,
    overlay_path: Path,
    assets_path: Path = DEFAULT_ASSETS,
) -> WorldDefinition:
    imported = ImportedBundle.model_validate(_load_yaml(imported_path))
    overlay = WorldOverlay.model_validate(_load_yaml(overlay_path))
    asset_manifest = AssetManifest.model_validate(_load_yaml(assets_path)).as_registry()
    imported_maps = {source_map.id: source_map for source_map in imported.maps}
    imported_maps_by_constant = {
        source_map.source_constant: source_map for source_map in imported.maps
    }
    if len(imported_maps_by_constant) != len(imported.maps):
        raise CompileError("imported source map constants must be unique")
    tile_definitions = {tile.id: tile for tile in overlay.tile_definitions}
    if len(tile_definitions) != len(overlay.tile_definitions):
        raise CompileError("tile definition ids must be unique")

    overlays_by_id = {map_overlay.id: map_overlay for map_overlay in overlay.maps}
    if len(overlays_by_id) != len(overlay.maps):
        raise CompileError("map overlay ids must be unique")
    runtime_ids_by_source_constant: dict[str, str] = {}
    for map_overlay in overlay.maps:
        source_map = imported_maps.get(map_overlay.source_map)
        if source_map is None:
            raise CompileError(f"overlay references unknown imported map {map_overlay.source_map}")
        if source_map.source_constant in runtime_ids_by_source_constant:
            raise CompileError(
                f"multiple overlays reference source map constant {source_map.source_constant}"
            )
        runtime_ids_by_source_constant[source_map.source_constant] = map_overlay.id

    maps: dict[str, MapDefinition] = {}
    for map_overlay in overlay.maps:
        source_map = imported_maps[map_overlay.source_map]
        maps[map_overlay.id] = _compile_map(
            source_map,
            map_overlay,
            tile_definitions,
            imported.source.repository,
            imported.source.revision,
            imported_maps,
            imported_maps_by_constant,
            overlays_by_id,
            runtime_ids_by_source_constant,
        )
    return WorldDefinition(
        start_map=overlay.start_map,
        player_appearance=overlay.player_appearance,
        asset_manifest=asset_manifest,
        maps=maps,
    )


def _compile_map(
    source_map: ImportedMap,
    overlay: MapOverlay,
    tile_definitions: dict[str, TileDefinition],
    repository: str,
    revision: str,
    imported_maps: dict[str, ImportedMap],
    imported_maps_by_constant: dict[str, ImportedMap],
    overlays_by_id: dict[str, MapOverlay],
    runtime_ids_by_source_constant: dict[str, str],
) -> MapDefinition:
    missing_surfaces = set(("walkable", "grass", "water", "blocked")) - overlay.terrain_tiles.keys()
    if missing_surfaces:
        raise CompileError(f"map {overlay.id} has no tile mapping for {sorted(missing_surfaces)}")

    rows = [[overlay.terrain_tiles[surface] for surface in row] for row in source_map.surfaces]
    for visual_override in overlay.visual_overrides:
        position = visual_override.position
        if not _contains(source_map, position.x, position.y):
            raise CompileError(f"visual override in {overlay.id} is outside map bounds")
        _require_tile(visual_override.tile, tile_definitions)
        original_tile = _require_tile(rows[position.y][position.x], tile_definitions)
        replacement = tile_definitions[visual_override.tile]
        original_collision = (original_tile.walkable, original_tile.surfable)
        replacement_collision = (replacement.walkable, replacement.surfable)
        if original_collision != replacement_collision:
            raise CompileError(
                f"visual override at ({position.x}, {position.y}) in {overlay.id} "
                "changes source collision"
            )
        rows[position.y][position.x] = replacement.id

    for row in rows:
        for tile_id in row:
            _require_tile(tile_id, tile_definitions)

    source_objects = {
        source_object.source_id: source_object for source_object in source_map.objects
    }
    npcs: list[NPCDefinition] = []
    for npc_overlay in overlay.npcs:
        source_object = source_objects.get(npc_overlay.source_object)
        if source_object is None:
            raise CompileError(f"NPC {npc_overlay.id} references unknown source object")
        facing = npc_overlay.facing or _source_facing(source_object.facing)
        npcs.append(
            NPCDefinition(
                id=npc_overlay.id,
                name=npc_overlay.name,
                position=source_object.position,
                facing=facing,
                dialog=npc_overlay.dialog,
                appearance=npc_overlay.appearance,
            )
        )

    transitions: list[TransitionDefinition] = []
    for transition in overlay.transitions:
        source_warp = _find_source_warp(source_map, overlay, transition)
        target_map_id, target_position = _resolve_warp_destination(
            source_warp,
            overlay,
            transition,
            imported_maps,
            imported_maps_by_constant,
            overlays_by_id,
            runtime_ids_by_source_constant,
        )
        transitions.append(
            TransitionDefinition(
                position=source_warp.position,
                target_map=target_map_id,
                target_position=target_position,
                target_facing=transition.target_facing,
            )
        )

    return MapDefinition(
        id=overlay.id,
        name=overlay.name,
        width=source_map.block_width * 2,
        height=source_map.block_height * 2,
        tiles=rows,
        tile_definitions=tile_definitions,
        player_spawn=overlay.player_spawn,
        npcs=npcs,
        transitions=transitions,
        source=SourceReference(
            repository=repository,
            revision=revision,
            map_name=source_map.source_name,
        ),
    )


def _find_source_warp(
    source_map: ImportedMap,
    overlay: MapOverlay,
    transition: TransitionOverlay,
) -> ImportedWarp:
    matches = [warp for warp in source_map.warps if warp.position == transition.source_position]
    if not matches:
        position = transition.source_position
        raise CompileError(
            f"transition at ({position.x}, {position.y}) in {overlay.id} is not a source warp"
        )
    if len(matches) > 1:
        raise CompileError(f"multiple source warps occupy the transition in {overlay.id}")
    return matches[0]


def _resolve_warp_destination(
    source_warp: ImportedWarp,
    overlay: MapOverlay,
    transition: TransitionOverlay,
    imported_maps: dict[str, ImportedMap],
    imported_maps_by_constant: dict[str, ImportedMap],
    overlays_by_id: dict[str, MapOverlay],
    runtime_ids_by_source_constant: dict[str, str],
) -> tuple[str, Position]:
    if source_warp.target_map_constant == "LAST_MAP":
        if transition.last_map_context is None:
            raise CompileError(
                f"LAST_MAP transition at warp {source_warp.index} in {overlay.id} "
                "requires last_map_context"
            )
        target_overlay = overlays_by_id.get(transition.last_map_context)
        if target_overlay is None:
            raise CompileError(
                f"LAST_MAP context {transition.last_map_context!r} is not a runtime map"
            )
        target_source = imported_maps[target_overlay.source_map]
        target_map_id = target_overlay.id
    else:
        if transition.last_map_context is not None:
            raise CompileError(
                f"non-LAST_MAP transition at warp {source_warp.index} in {overlay.id} "
                "cannot declare last_map_context"
            )
        target_source_candidate = imported_maps_by_constant.get(source_warp.target_map_constant)
        if target_source_candidate is None:
            raise CompileError(
                f"source warp targets unavailable map constant {source_warp.target_map_constant}"
            )
        target_source = target_source_candidate
        target_map_id = runtime_ids_by_source_constant.get(target_source.source_constant, "")
        if not target_map_id:
            raise CompileError(
                f"source warp target {target_source.source_constant} has no runtime map overlay"
            )

    destination = next(
        (warp for warp in target_source.warps if warp.index == source_warp.target_warp),
        None,
    )
    if destination is None:
        raise CompileError(
            f"source warp {source_warp.index} in {overlay.id} targets missing warp "
            f"{source_warp.target_warp} in {target_source.source_constant}"
        )
    return target_map_id, destination.position


def _contains(source_map: ImportedMap, x: int, y: int) -> bool:
    return 0 <= x < source_map.block_width * 2 and 0 <= y < source_map.block_height * 2


def _require_tile(tile_id: str, definitions: dict[str, TileDefinition]) -> TileDefinition:
    try:
        return definitions[tile_id]
    except KeyError as error:
        raise CompileError(f"unknown tile definition {tile_id!r}") from error


def _source_facing(source_facing: str) -> Direction:
    mapping = {
        "UP": Direction.NORTH,
        "DOWN": Direction.SOUTH,
        "LEFT": Direction.WEST,
        "RIGHT": Direction.EAST,
        "ANY_DIR": Direction.SOUTH,
        "NONE": Direction.SOUTH,
    }
    try:
        return mapping[source_facing]
    except KeyError as error:
        raise CompileError(f"unsupported source facing value {source_facing}") from error


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile validated YAML into runtime JSON.")
    parser.add_argument("--imported", type=Path, default=DEFAULT_IMPORTED)
    parser.add_argument("--overlay", type=Path, default=DEFAULT_OVERLAY)
    parser.add_argument("--assets", type=Path, default=DEFAULT_ASSETS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()

    try:
        world = compile_world(arguments.imported, arguments.overlay, arguments.assets)
    except Exception as error:
        print(f"data compilation failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    rendered = json.dumps(world.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"

    if arguments.check:
        try:
            existing = arguments.output.read_text(encoding="utf-8")
        except OSError as error:
            print(f"missing compiled data: {arguments.output}", file=sys.stderr)
            raise SystemExit(1) from error
        if existing != rendered:
            print("compiled game data is stale; rerun the compiler", file=sys.stderr)
            raise SystemExit(1)
        print(f"data check passed: {arguments.output}")
        return

    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(rendered, encoding="utf-8")
    print(f"wrote {arguments.output}")


if __name__ == "__main__":
    main()
