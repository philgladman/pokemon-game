from __future__ import annotations

import re

from .errors import ParseError


def parse_rgbds_constants(content: str) -> dict[str, int]:
    """Parse the small RGBDS const/alias subset used by story source files."""

    values: dict[str, int] = {}
    current = 0
    for raw_line in content.splitlines():
        line = raw_line.split(";", 1)[0].strip()
        if not line:
            continue
        if re.fullmatch(r"const_def(?:\s+([^\s]+))?", line):
            token = line.split(maxsplit=1)[1] if " " in line else "0"
            current = _number(token)
            continue
        match = re.fullmatch(r"const_next\s+([^\s]+)", line)
        if match:
            current = _number(match.group(1))
            continue
        match = re.fullmatch(r"const_skip(?:\s+([^\s]+))?", line)
        if match:
            current += _number(match.group(1) or "1")
            continue
        match = re.fullmatch(r"const(?:_export)?\s+([A-Z0-9_]+)", line)
        if match:
            values[match.group(1)] = current
            current += 1
            continue
        match = re.fullmatch(r"DEF\s+([A-Z0-9_]+)\s+EQU\s+([A-Z0-9_$]+)", line)
        if match:
            target = match.group(2)
            values[match.group(1)] = values.get(target, _number(target))
    return values


def require_constants(values: dict[str, int], names: set[str]) -> dict[str, int]:
    missing = names - values.keys()
    if missing:
        raise ParseError(f"missing source constants: {sorted(missing)}")
    return {name: values[name] for name in names}


def _number(token: str) -> int:
    if token.startswith("$"):
        return int(token[1:], 16)
    if token.isdigit():
        return int(token)
    # Alias callers use dict.get's eager default, so a known symbol may arrive here.
    return -1
