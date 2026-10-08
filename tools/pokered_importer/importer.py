from __future__ import annotations

import hashlib
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from backend.app.models.common import Position
from backend.app.models.source import (
    ImportedBundle,
    ImportedMap,
    ImportedObject,
    ImportedWarp,
    SourceProvenance,
    Surface,
)

REPOSITORY_URL = "https://github.com/pret/pokered"
COLLISION_SAMPLE_OFFSETS = (4, 6, 12, 14)


class ImporterError(RuntimeError):
    """Raised when the pinned source no longer matches supported Phase 1 syntax."""


@dataclass(frozen=True)
class MapSpec:
    id: str
    source_name: str
    constant: str
    tileset: str
    collision_label: str
    blockset_name: str


MAP_SPECS = (
    MapSpec("pallet_town", "PalletTown", "PALLET_TOWN", "OVERWORLD", "Overworld_Coll", "overworld"),
    MapSpec(
        "reds_house_1f",
        "RedsHouse1F",
        "REDS_HOUSE_1F",
        "REDS_HOUSE_1",
        "RedsHouse1_Coll",
        "reds_house",
    ),
)


def import_pallet_town(source_root: Path) -> ImportedBundle:
    source_root = source_root.resolve()
    _require_paths(source_root)
    revision = _git_revision(source_root)
    dimensions_text = _read_text(source_root / "constants/map_constants.asm")
    collision_text = _read_text(source_root / "data/tilesets/collision_tile_ids.asm")

    maps: list[ImportedMap] = []
    referenced_files: set[Path] = {
        source_root / "constants/map_constants.asm",
        source_root / "data/tilesets/collision_tile_ids.asm",
    }
    for spec in MAP_SPECS:
        object_path = source_root / f"data/maps/objects/{spec.source_name}.asm"
        header_path = source_root / f"data/maps/headers/{spec.source_name}.asm"
        block_path = source_root / f"maps/{spec.source_name}.blk"
        blockset_path = source_root / f"gfx/blocksets/{spec.blockset_name}.bst"
        referenced_files.update((object_path, header_path, block_path, blockset_path))

        width, height = _parse_dimensions(dimensions_text, spec.constant)
        _validate_header(_read_text(header_path), spec)
        passable_tiles = _parse_collision_tiles(collision_text, spec.collision_label)
        blocks = _parse_blocks(block_path.read_bytes(), width, height, block_path)
        tile_ids = _expand_collision_tiles(blocks, blockset_path.read_bytes())
        objects, warps = _parse_objects(_read_text(object_path))
        surfaces = [
            [_surface_for(tile_id, passable_tiles, spec.tileset) for tile_id in row]
            for row in tile_ids
        ]
        maps.append(
            ImportedMap(
                id=spec.id,
                source_name=spec.source_name,
                source_constant=spec.constant,
                tileset=spec.tileset,
                block_width=width,
                block_height=height,
                source_blocks=blocks,
                source_tile_ids=tile_ids,
                surfaces=surfaces,
                warps=warps,
                objects=objects,
            )
        )

    hashes = {
        str(path.relative_to(source_root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(referenced_files)
    }
    return ImportedBundle(
        source=SourceProvenance(repository=REPOSITORY_URL, revision=revision, files=hashes),
        maps=maps,
    )


def _require_paths(source_root: Path) -> None:
    if not source_root.is_dir():
        raise ImporterError(f"pret/pokered source directory does not exist: {source_root}")
    if not (source_root / ".git").exists():
        raise ImporterError(f"source directory is not a Git checkout: {source_root}")


def _git_revision(source_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=source_root,
        check=False,
        capture_output=True,
        text=True,
    )
    revision = result.stdout.strip()
    if result.returncode != 0 or re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise ImporterError("unable to identify the pret/pokered Git revision")
    return revision


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise ImporterError(f"unable to read required source file: {path}") from error


def _parse_dimensions(content: str, constant: str) -> tuple[int, int]:
    match = re.search(
        rf"^\s*map_const\s+{re.escape(constant)},\s*(\d+),\s*(\d+)(?:\s*;.*)?$",
        content,
        re.MULTILINE,
    )
    if match is None:
        raise ImporterError(f"unsupported or missing map_const for {constant}")
    return int(match.group(1)), int(match.group(2))


def _validate_header(content: str, spec: MapSpec) -> None:
    expected = rf"^\s*map_header\s+{spec.source_name},\s*{spec.constant},\s*{spec.tileset}\s*$"
    if re.search(expected, content, re.MULTILINE) is None:
        raise ImporterError(f"unsupported map header for {spec.source_name}")


def _parse_collision_tiles(content: str, label: str) -> set[int]:
    match = re.search(
        rf"^{re.escape(label)}::\s*$\n(?:[A-Za-z0-9_]+::\s*$\n)?\s*coll_tiles\s+([^\n;]+)",
        content,
        re.MULTILINE,
    )
    if match is None:
        raise ImporterError(f"unsupported or missing collision list {label}")
    try:
        return {int(token.strip().removeprefix("$"), 16) for token in match.group(1).split(",")}
    except ValueError as error:
        raise ImporterError(f"unsupported collision tile value in {label}") from error


def _parse_blocks(content: bytes, width: int, height: int, path: Path) -> list[list[int]]:
    expected = width * height
    if len(content) != expected:
        raise ImporterError(f"{path} contains {len(content)} blocks; expected {expected}")
    return [list(content[offset : offset + width]) for offset in range(0, expected, width)]


def _expand_collision_tiles(blocks: list[list[int]], blockset: bytes) -> list[list[int]]:
    rows: list[list[int]] = []
    for block_row in blocks:
        upper: list[int] = []
        lower: list[int] = []
        for block_id in block_row:
            offset = block_id * 16
            block = blockset[offset : offset + 16]
            if len(block) != 16:
                raise ImporterError(f"block id {block_id:#x} is outside the blockset")
            upper.extend((block[COLLISION_SAMPLE_OFFSETS[0]], block[COLLISION_SAMPLE_OFFSETS[1]]))
            lower.extend((block[COLLISION_SAMPLE_OFFSETS[2]], block[COLLISION_SAMPLE_OFFSETS[3]]))
        rows.extend((upper, lower))
    return rows


def _parse_objects(content: str) -> tuple[list[ImportedObject], list[ImportedWarp]]:
    constants = re.findall(r"^\s*const_export\s+([A-Z0-9_]+)\s*$", content, re.MULTILINE)
    object_matches = re.findall(r"^\s*object_event\s+([^;\n]+)", content, re.MULTILINE)
    if len(constants) != len(object_matches):
        raise ImporterError(
            "object constants and object_event entries do not have a one-to-one mapping"
        )

    objects: list[ImportedObject] = []
    for source_id, arguments in zip(constants, object_matches, strict=True):
        fields = [field.strip() for field in arguments.split(",")]
        if len(fields) != 6:
            raise ImporterError(f"unsupported object_event for {source_id}: {arguments}")
        try:
            position = Position(x=int(fields[0]), y=int(fields[1]))
        except ValueError as error:
            raise ImporterError(f"non-numeric object position for {source_id}") from error
        objects.append(
            ImportedObject(
                source_id=source_id.lower(),
                position=position,
                sprite=fields[2],
                movement=fields[3],
                facing=fields[4],
                text_reference=fields[5],
            )
        )

    warps: list[ImportedWarp] = []
    warp_events = re.findall(r"^\s*warp_event\s+([^;\n]+)", content, re.MULTILINE)
    for index, arguments in enumerate(warp_events, start=1):
        fields = [field.strip() for field in arguments.split(",")]
        if len(fields) != 4:
            raise ImporterError(f"unsupported warp_event: {arguments}")
        try:
            warps.append(
                ImportedWarp(
                    index=index,
                    position=Position(x=int(fields[0]), y=int(fields[1])),
                    target_map_constant=fields[2],
                    target_warp=int(fields[3]),
                )
            )
        except ValueError as error:
            raise ImporterError(f"non-numeric warp_event value: {arguments}") from error
    return objects, warps


def _surface_for(tile_id: int, passable_tiles: set[int], tileset: str) -> Surface:
    if tileset == "OVERWORLD" and tile_id == 0x14:
        return "water"
    if tileset == "OVERWORLD" and tile_id == 0x52:
        return "grass"
    return "walkable" if tile_id in passable_tiles else "blocked"
