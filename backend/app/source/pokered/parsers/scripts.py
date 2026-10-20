from __future__ import annotations

import re

from backend.app.models.common import Direction, Position

from .errors import ParseError

_DIRECTIONS = {
    "PAD_UP": Direction.NORTH,
    "PAD_DOWN": Direction.SOUTH,
    "PAD_LEFT": Direction.WEST,
    "PAD_RIGHT": Direction.EAST,
    "NPC_MOVEMENT_UP": Direction.NORTH,
    "NPC_MOVEMENT_DOWN": Direction.SOUTH,
    "NPC_MOVEMENT_LEFT": Direction.WEST,
    "NPC_MOVEMENT_RIGHT": Direction.EAST,
}


def label_body(content: str, label: str) -> str:
    match = re.search(rf"^{re.escape(label)}(?:::?)?\s*$", content, re.MULTILINE)
    if match is None:
        raise ParseError(f"missing source label {label}")
    following = content[match.end() :]
    end = re.search(r"^[A-Z_.][A-Za-z0-9_.]*(?:::?)?\s*$", following, re.MULTILINE)
    return following[: end.start()] if end else following


def parse_movement(content: str, label: str, *, rle: bool) -> tuple[Direction, ...]:
    return parse_movement_sequence(content, (label,), rle=rle)


def parse_simulated_joypad_rle(content: str, label: str) -> tuple[Direction, ...]:
    """Expand a forward-written RLE buffer into its backward-consumed execution order."""

    return tuple(reversed(parse_movement(content, label, rle=True)))


def parse_movement_sequence(
    content: str,
    labels: tuple[str, ...],
    *,
    rle: bool,
) -> tuple[Direction, ...]:
    """Parse one movement path, including assembly-label fallthrough paths."""

    if not labels:
        raise ParseError("movement sequence requires at least one source label")
    steps: list[Direction] = []
    found_end = False
    for label_index, label in enumerate(labels):
        body = label_body(content, label)
        for directive in re.findall(r"^\s*db\s+([^;\n]+)", body, re.MULTILINE):
            fields = [field.strip() for field in directive.split(",")]
            if fields[0] == "-1":
                found_end = True
                break
            direction = _DIRECTIONS.get(fields[0])
            if direction is None:
                if fields[0] == "NPC_CHANGE_FACING":
                    continue
                raise ParseError(f"unsupported movement {fields[0]} in {label}")
            if rle:
                if len(fields) != 2 or not fields[1].isdigit():
                    raise ParseError(f"invalid RLE movement in {label}: {directive}")
                steps.extend([direction] * int(fields[1]))
            else:
                if len(fields) != 1:
                    raise ParseError(f"invalid plain movement in {label}: {directive}")
                steps.append(direction)
        if found_end:
            if label_index != len(labels) - 1:
                raise ParseError(f"movement {label} terminates before its declared fallthrough")
            break
    if not found_end:
        raise ParseError(f"movement {labels[-1]} is missing its -1 terminator")
    return tuple(steps)


def parse_new_game_warp(content: str) -> tuple[str, Position]:
    body = label_body(content, "NewGameWarp")
    match = re.search(
        r"^\s*special_warp_spec\s+([A-Z0-9_]+),\s*(\d+),\s*(\d+),",
        body,
        re.MULTILINE,
    )
    if match is None:
        raise ParseError("NewGameWarp is missing its special_warp_spec")
    return match.group(1), Position(x=int(match.group(2)), y=int(match.group(3)))


def assert_source_patterns(content: str, patterns: dict[str, str], file: str) -> None:
    for description, pattern in patterns.items():
        if re.search(pattern, content, re.MULTILINE) is None:
            raise ParseError(f"{file} source drift: missing {description}")
