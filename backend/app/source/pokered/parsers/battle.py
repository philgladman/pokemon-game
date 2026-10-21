"""Parse the data subset needed by the level-five lab battle."""

from __future__ import annotations

import re

from backend.app.models.battle import BattleProvenance, MoveDefinition, MoveEffect, PokemonStats

from .errors import ParseError

SUPPORTED_EFFECTS: dict[str, MoveEffect] = {
    "NO_ADDITIONAL_EFFECT": "damage",
    "ATTACK_DOWN1_EFFECT": "attack_down",
    "DEFENSE_DOWN1_EFFECT": "defense_down",
    "RECOIL_EFFECT": "recoil",
}


def source_lines(content: str) -> tuple[str, ...]:
    return tuple(line for raw in content.splitlines() if (line := raw.split(";", 1)[0].strip()))


def parse_starter_base(
    content: str,
) -> tuple[PokemonStats, tuple[str, str], tuple[str, ...], int, str]:
    rows = [line[3:].strip() for line in source_lines(content) if line.startswith("db ")]
    if len(rows) != 8:
        raise ParseError("unsupported starter base-stat record")
    try:
        numbers = tuple(int(token.strip()) for token in rows[1].split(","))
        if len(numbers) != 5:
            raise ValueError("expected five base stats")
        types = tuple(token.strip() for token in rows[2].split(","))
        if len(types) != 2:
            raise ValueError("expected two types")
        slots = tuple(token.strip() for token in rows[5].split(","))
        if len(slots) != 4 or slots[2:] != ("NO_MOVE", "NO_MOVE"):
            raise ValueError("expected two initial moves and two empty slots")
        return (
            PokemonStats(
                **dict(zip(("hp", "attack", "defense", "speed", "special"), numbers, strict=True))
            ),
            (types[0], types[1]),
            slots[:2],
            int(rows[4]),
            rows[6],
        )
    except ValueError as error:
        raise ParseError(f"unsupported starter base stats: {error}") from error


def validate_level_five_learnset(content: str, symbol: str) -> None:
    match = re.search(rf"^{symbol}:\s*$(.*?)(?=^[A-Za-z]\w*:|\Z)", content, re.M | re.S)
    if match is None:
        raise ParseError(f"missing learnset {symbol}")
    rows = source_lines(match.group(1))
    try:
        first_zero = rows.index("db 0")
    except ValueError as error:
        raise ParseError(f"missing evolution terminator {symbol}") from error
    learned = rows[first_zero + 1 :]
    if not learned or learned[-1] != "db 0":
        raise ParseError(f"missing learnset terminator {symbol}")
    previous = 0
    for row in learned[:-1]:
        entry = re.fullmatch(r"db\s+(\d+),\s*([A-Z_]+)", row)
        if entry is None:
            raise ParseError(f"unsupported learnset row {symbol}: {row}")
        level = int(entry[1])
        if level <= 6 or level < previous:
            raise ParseError(f"unsupported level-six learnset drift in {symbol}")
        previous = level


def parse_battle_moves(
    content: str, constants: dict[str, int], provenance: BattleProvenance
) -> tuple[MoveDefinition, ...]:
    names = {"TACKLE", "SCRATCH", "GROWL", "TAIL_WHIP", "STRUGGLE"}
    found: dict[str, MoveDefinition] = {}
    for line in source_lines(content):
        match = re.fullmatch(
            r"move\s+([A-Z_]+),\s*([A-Z0-9_]+),\s*(\d+),\s*([A-Z_]+),\s*(\d+),\s*(\d+)",
            line,
        )
        if match is None or match[1] not in names:
            continue
        name, effect, power, move_type, percent, pp = match.groups()
        if name in found or effect not in SUPPORTED_EFFECTS or name not in constants:
            raise ParseError(f"unsupported or duplicate battle move {name}")
        found[name] = MoveDefinition(
            id=constants[name],
            constant=name,
            effect=SUPPORTED_EFFECTS[effect],
            power=int(power),
            type=move_type,
            accuracy=int(percent) * 255 // 100,
            pp=int(pp),
            provenance=provenance,
        )
    if found.keys() != names:
        raise ParseError(f"missing supported battle moves: {sorted(names - found.keys())}")
    return tuple(found[name] for name in sorted(names))


def parse_stat_ratios(content: str) -> tuple[tuple[int, int], ...]:
    rows = source_lines(content)
    if not rows or rows[0] != "StatModifierRatios:":
        raise ParseError("missing StatModifierRatios")
    result = []
    for row in rows[1:]:
        match = re.fullmatch(r"db\s+(\d+),\s*(\d+)", row)
        if match is None or int(match[2]) == 0:
            raise ParseError(f"unsupported stat ratio: {row}")
        result.append((int(match[1]), int(match[2])))
    if len(result) != 13:
        raise ParseError("expected thirteen stat modifier ratios")
    return tuple(result)


def parse_first_rival_parties(content: str) -> tuple[str, str, str]:
    match = re.search(r"^Rival1Data:\s*$(.*?)(?=^[A-Za-z]\w*:|\Z)", content, re.M | re.S)
    if match is None:
        raise ParseError("missing Rival1Data")
    rows = source_lines(match.group(1))[:3]
    species = []
    for row in rows:
        entry = re.fullmatch(r"db\s+5,\s*([A-Z_]+),\s*0", row)
        if entry is None:
            raise ParseError("unsupported first rival party")
        species.append(entry[1])
    if len(species) != 3:
        raise ParseError("expected three first rival parties")
    return species[0], species[1], species[2]
