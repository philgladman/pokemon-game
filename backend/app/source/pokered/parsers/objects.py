from __future__ import annotations

import re
from dataclasses import dataclass

from backend.app.models.common import Direction, Position

from .errors import ParseError


@dataclass(frozen=True)
class ParsedObject:
    source_id: str
    object_index: int
    position: Position
    sprite: str
    movement: str
    facing: str
    text_reference: str


@dataclass(frozen=True)
class ParsedWarp:
    index: int
    position: Position
    target_map: str
    target_warp: int


@dataclass(frozen=True)
class ParsedBackgroundEvent:
    position: Position
    text_reference: str


@dataclass(frozen=True)
class ParsedMapObjects:
    objects: tuple[ParsedObject, ...]
    warps: tuple[ParsedWarp, ...]
    background_events: tuple[ParsedBackgroundEvent, ...]


def parse_map_objects(content: str) -> ParsedMapObjects:
    constants = re.findall(r"^\s*const_export\s+([A-Z0-9_]+)\s*$", content, re.MULTILINE)
    object_events = re.findall(r"^\s*object_event\s+([^;\n]+)", content, re.MULTILINE)
    if len(constants) != len(object_events):
        raise ParseError("object constants and object_event entries must have a one-to-one mapping")

    objects: list[ParsedObject] = []
    for index, (source_id, arguments) in enumerate(
        zip(constants, object_events, strict=True), start=1
    ):
        fields = [field.strip() for field in arguments.split(",")]
        if len(fields) < 6:
            raise ParseError(f"unsupported object_event for {source_id}: {arguments}")
        try:
            position = Position(x=int(fields[0]), y=int(fields[1]))
        except ValueError as error:
            raise ParseError(f"non-numeric object position for {source_id}") from error
        objects.append(
            ParsedObject(
                source_id,
                index,
                position,
                fields[2],
                fields[3],
                fields[4],
                fields[5],
            )
        )

    warps = tuple(
        _parse_warp(index, arguments)
        for index, arguments in enumerate(
            re.findall(r"^\s*warp_event\s+([^;\n]+)", content, re.MULTILINE), start=1
        )
    )
    background_events = tuple(
        _parse_background(arguments)
        for arguments in re.findall(r"^\s*bg_event\s+([^;\n]+)", content, re.MULTILINE)
    )
    return ParsedMapObjects(tuple(objects), warps, background_events)


def _parse_warp(index: int, arguments: str) -> ParsedWarp:
    fields = [field.strip() for field in arguments.split(",")]
    if len(fields) != 4:
        raise ParseError(f"unsupported warp_event: {arguments}")
    try:
        return ParsedWarp(
            index,
            Position(x=int(fields[0]), y=int(fields[1])),
            fields[2],
            int(fields[3]),
        )
    except ValueError as error:
        raise ParseError(f"non-numeric warp_event value: {arguments}") from error


def _parse_background(arguments: str) -> ParsedBackgroundEvent:
    fields = [field.strip() for field in arguments.split(",")]
    if len(fields) != 3:
        raise ParseError(f"unsupported bg_event: {arguments}")
    try:
        return ParsedBackgroundEvent(Position(x=int(fields[0]), y=int(fields[1])), fields[2])
    except ValueError as error:
        raise ParseError(f"non-numeric bg_event value: {arguments}") from error


def source_facing(value: str) -> Direction:
    return {
        "UP": Direction.NORTH,
        "DOWN": Direction.SOUTH,
        "LEFT": Direction.WEST,
        "RIGHT": Direction.EAST,
        "ANY_DIR": Direction.SOUTH,
        "NONE": Direction.SOUTH,
    }.get(value, Direction.SOUTH)
