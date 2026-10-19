from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from backend.app.models.common import Direction

from .errors import ParseError


@dataclass(frozen=True)
class ParsedConnection:
    direction: Direction
    target_map: str
    offset: int


@dataclass(frozen=True)
class ParsedHeader:
    source_name: str
    map_constant: str
    tileset: str
    connections: tuple[ParsedConnection, ...]


@dataclass(frozen=True)
class ParsedMapMetadata:
    kind: Literal["outdoor", "indoor"]
    last_map_target: str | None


def parse_dimensions(content: str, map_constant: str) -> tuple[int, int]:
    match = re.search(
        rf"^\s*map_const\s+{re.escape(map_constant)},\s*(\d+),\s*(\d+)(?:\s*;.*)?$",
        content,
        re.MULTILINE,
    )
    if match is None:
        raise ParseError(f"missing map_const for {map_constant}")
    return int(match.group(1)), int(match.group(2))


def parse_map_metadata(content: str) -> dict[str, ParsedMapMetadata]:
    result: dict[str, ParsedMapMetadata] = {}
    indoor_maps: list[str] = []
    inside_indoor_section = False
    for line in content.splitlines():
        if re.match(r"\s*DEF\s+FIRST_INDOOR_MAP\s+EQU", line):
            inside_indoor_section = True
            continue
        map_match = re.match(r"\s*map_const\s+([A-Z0-9_]+),", line)
        if map_match:
            map_id = map_match.group(1)
            if inside_indoor_section:
                indoor_maps.append(map_id)
            else:
                result[map_id] = ParsedMapMetadata("outdoor", None)
            continue
        group_end = re.match(r"\s*end_indoor_group\s+([A-Z0-9_]+)", line)
        if group_end:
            target = group_end.group(1)
            for map_id in indoor_maps:
                result[map_id] = ParsedMapMetadata("indoor", target)
            indoor_maps = []
    if indoor_maps:
        raise ParseError("unterminated indoor map group")
    return result


def parse_header(content: str) -> ParsedHeader:
    match = re.search(
        r"^\s*map_header\s+([A-Za-z0-9_]+),\s*([A-Z0-9_]+),\s*([A-Z0-9_]+)\s*$",
        content,
        re.MULTILINE,
    )
    if match is None:
        raise ParseError("missing or unsupported map_header")
    connections = tuple(
        ParsedConnection(Direction(direction), target_map, int(offset))
        for direction, _source_name, target_map, offset in re.findall(
            r"^\s*connection\s+(north|south|east|west),\s*([A-Za-z0-9_]+),\s*"
            r"([A-Z0-9_]+),\s*(-?\d+)\s*$",
            content,
            re.MULTILINE,
        )
    )
    return ParsedHeader(match.group(1), match.group(2), match.group(3), connections)


def parse_blocks(content: bytes, width: int, height: int, path: Path) -> list[list[int]]:
    expected = width * height
    if len(content) != expected:
        raise ParseError(f"{path} contains {len(content)} blocks; expected {expected}")
    return [list(content[offset : offset + width]) for offset in range(0, expected, width)]


def expand_blocks(blocks: list[list[int]], blockset: bytes) -> list[list[int]]:
    rows: list[list[int]] = []
    for block_row in blocks:
        expanded: list[list[int]] = [[], [], [], []]
        for block_id in block_row:
            block = _block(blockset, block_id)
            for row_index in range(4):
                start = row_index * 4
                expanded[row_index].extend(block[start : start + 4])
        rows.extend(expanded)
    return rows


def expand_collision_tiles(blocks: list[list[int]], blockset: bytes) -> list[list[int]]:
    rows: list[list[int]] = []
    for block_row in blocks:
        upper: list[int] = []
        lower: list[int] = []
        for block_id in block_row:
            block = _block(blockset, block_id)
            upper.extend((block[4], block[6]))
            lower.extend((block[12], block[14]))
        rows.extend((upper, lower))
    return rows


def _block(blockset: bytes, block_id: int) -> bytes:
    block = blockset[block_id * 16 : block_id * 16 + 16]
    if len(block) != 16:
        raise ParseError(f"block id {block_id:#x} is outside the blockset")
    return block
