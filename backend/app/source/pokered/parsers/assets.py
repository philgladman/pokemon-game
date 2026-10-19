from __future__ import annotations

import re

from .errors import ParseError


def parse_collision_sets(content: str) -> dict[str, set[int]]:
    result: dict[str, set[int]] = {}
    pending: list[str] = []
    for line in content.splitlines():
        label = re.fullmatch(r"([A-Za-z0-9_]+)_Coll::", line.strip())
        if label:
            pending.append(_constant_name(label.group(1)))
            continue
        values = re.match(r"\s*coll_tiles(?:\s+([^;]+))?", line)
        if values and pending:
            try:
                parsed = {
                    int(token.strip().removeprefix("$"), 16)
                    for token in (values.group(1) or "").split(",")
                    if token.strip()
                }
            except ValueError as error:
                raise ParseError("unsupported collision tile value") from error
            for alias in pending:
                result[alias] = parsed
            pending = []
    return result


def parse_incbin_aliases(content: str, suffix: str, directory: str) -> dict[str, str]:
    result: dict[str, str] = {}
    pending: list[str] = []
    pattern = re.compile(rf"([A-Za-z0-9_]+)_{re.escape(suffix)}::")
    incbin = re.compile(rf'INCBIN\s+"{re.escape(directory)}/([a-z0-9_]+)\.[^"]+"')
    for line in content.splitlines():
        labels = pattern.findall(line)
        if labels:
            pending.extend(_constant_name(label) for label in labels)
        source = incbin.search(line)
        if source and pending:
            for alias in pending:
                result[alias] = source.group(1)
            pending = []
        elif line.strip() and not labels and not line.lstrip().startswith(";"):
            pending = []
    return result


def parse_initial_visibility(content: str) -> dict[str, bool]:
    result: dict[str, bool] = {}
    active = False
    for line in content.splitlines():
        section = re.match(r"\s*toggleable_objects_for\s+([A-Z0-9_]+)", line)
        if section:
            active = True
            continue
        state = re.match(r"\s*toggle_object_state\s+([A-Z0-9_]+),\s*(ON|OFF)", line)
        if active and state:
            result[state.group(1)] = state.group(2) == "ON"
        elif active and line.strip() and not line.lstrip().startswith(";"):
            active = False
    return result


def parse_sprite_assets(pointer_content: str, graphics_content: str) -> dict[str, str]:
    labels_to_files = {
        f"{label}Sprite": filename
        for label, filename in re.findall(
            r"^([A-Za-z0-9_]+)Sprite::\s+INCBIN\s+"
            r'"gfx/sprites/([a-z0-9_]+)\.[^"]+"',
            graphics_content,
            re.MULTILINE,
        )
    }
    result: dict[str, str] = {}
    for label, sprite_constant in re.findall(
        r"^\s*overworld_sprite\s+([A-Za-z0-9_]+),\s*\d+\s*;\s*(SPRITE_[A-Z0-9_]+)",
        pointer_content,
        re.MULTILINE,
    ):
        filename = labels_to_files.get(label)
        if filename:
            result[sprite_constant] = filename
    return result


def _constant_name(value: str) -> str:
    return re.sub(r"(?<=[a-z])(?=[A-Z0-9])|(?<=[A-Za-z])(?=\d)", "_", value).upper()
