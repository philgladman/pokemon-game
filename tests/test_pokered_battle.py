from pathlib import Path

import pytest

from backend.app.models.battle import BattleProvenance
from backend.app.source.pokered import PokeredSource, PokeredSourceError
from backend.app.source.pokered.battle import _validate_rules
from backend.app.source.pokered.parsers import ParseError, parse_rgbds_constants
from backend.app.source.pokered.parsers.battle import (
    parse_battle_moves,
    parse_first_rival_parties,
    parse_starter_base,
    parse_stat_ratios,
    validate_level_five_learnset,
)

ROOT = Path(__file__).resolve().parents[1] / "external/pokered"


@pytest.mark.parametrize(
    "before,after",
    [
        ("45,  49,  49,  45,  65", "45, 49"),
        ("GRASS, POISON", "GRASS"),
        ("TACKLE, GROWL, NO_MOVE, NO_MOVE", "TACKLE, GROWL, LEECH_SEED, NO_MOVE"),
        ("db 0 ; padding", ""),
    ],
)
def test_base_record_rejects_unsupported_shapes(before: str, after: str) -> None:
    content = (ROOT / "data/pokemon/base_stats/bulbasaur.asm").read_text()
    assert before in content
    with pytest.raises(ParseError):
        parse_starter_base(content.replace(before, after))


@pytest.mark.parametrize(
    "replacement", ["db 5, LEECH_SEED", "db 6, LEECH_SEED", "db broken", "db 0"]
)
def test_level_five_learnset_drift_is_explicit(replacement: str) -> None:
    content = (ROOT / "data/pokemon/evos_moves.asm").read_text()
    with pytest.raises(ParseError):
        validate_level_five_learnset(
            content.replace("db 7, LEECH_SEED", replacement), "BulbasaurEvosMoves"
        )


@pytest.mark.parametrize("change", ["missing", "duplicate", "effect"])
def test_battle_move_parser_rejects_missing_duplicate_and_unsupported_effects(change: str) -> None:
    content = (ROOT / "data/moves/moves.asm").read_text()
    row = next(line for line in content.splitlines() if "move SCRATCH," in line)
    if change == "missing":
        content = content.replace(row, "")
    elif change == "duplicate":
        content += "\n" + row
    else:
        content = content.replace(row, row.replace("NO_ADDITIONAL_EFFECT", "BURN_SIDE_EFFECT1"))
    provenance = BattleProvenance(
        repository="fixture", revision="a" * 40, file="moves.asm", symbol="Moves"
    )
    with pytest.raises(ParseError):
        parse_battle_moves(
            content,
            parse_rgbds_constants((ROOT / "constants/move_constants.asm").read_text()),
            provenance,
        )


@pytest.mark.parametrize(
    "content", ["", "StatModifierRatios:\n db 1, 0", "StatModifierRatios:\n db 1, 1"]
)
def test_stat_ratios_reject_invalid_table(content: str) -> None:
    with pytest.raises(ParseError):
        parse_stat_ratios(content)


def test_rival_parties_require_level_five() -> None:
    content = (ROOT / "data/trainers/parties.asm").read_text()
    assert parse_first_rival_parties(content) == ("SQUIRTLE", "BULBASAUR", "CHARMANDER")
    with pytest.raises(ParseError):
        parse_first_rival_parties(content.replace("db 5, SQUIRTLE, 0", "db 6, SQUIRTLE, 0"))


@pytest.mark.parametrize(
    "file,before,after",
    [
        ("engine/battle/core.asm", "cp 75 percent - 1", "cp 75 percent"),
        ("engine/battle/core.asm", "\trlc a\n\trlc a\n\trlc a", "\trlc a"),
        ("engine/battle/core.asm", "cp 85 percent + 1", "cp 85 percent"),
        ("engine/battle/effects.asm", "cp 25 percent + 1", "cp 25 percent"),
        (
            "scripts/OaksLab.asm",
            "\tld a, $3\n.done\n\tld [wTrainerNo], a",
            "\tld a, $2\n.done\n\tld [wTrainerNo], a",
        ),
        ("engine/battle/trainer_ai.asm", "\tcall Random\n\tjp hl", "\tjp hl"),
        ("home/move_mon.asm", "\tsbc d               ; test", "\tadc d               ; test"),
        ("home/trainers2.asm", "\tld de, wTrainerBaseMoney", "\tld de, wTrainerBaseMoney + 1"),
        ("engine/battle/read_trainer_party.asm", "\tld c, 2 ;", "\tld c, 3 ;"),
        ("engine/battle/experience.asm", "\tcall nz, BoostExp", "\tcall z, BoostExp"),
        (
            "engine/events/heal_party.asm",
            "\tld hl, MON_MAXHP - MON_HP",
            "\tld hl, MON_MAXHP - MON_HP + 1",
        ),
        (
            "engine/battle/core.asm",
            "\tcall FaintEnemyPokemon\n\tcall AnyPartyAlive",
            "\tcall FaintEnemyPokemon",
        ),
    ],
)
def test_executable_rule_drift_is_rejected(file: str, before: str, after: str) -> None:
    original = (ROOT / file).read_text()
    assert before in original

    def read(relative: str) -> str:
        content = (ROOT / relative).read_text()
        return content.replace(before, after) if relative == file else content

    with pytest.raises(ParseError, match="source drift"):
        _validate_rules(read)


def test_battle_builder_is_cached_and_wraps_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    source = PokeredSource(ROOT)
    definition = source.build_battle()
    assert source.build_battle() is definition
    another = PokeredSource(ROOT)

    def broken(*args: object) -> None:
        raise ParseError("fixture drift")

    monkeypatch.setattr("backend.app.source.pokered.source.build_first_battle", broken)
    with pytest.raises(PokeredSourceError, match=r"first battle.*fixture drift"):
        another.build_battle()
