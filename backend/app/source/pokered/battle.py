"""Compile the supported first battle without an assembly interpreter."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from backend.app.models.battle import (
    BattleDefinition,
    BattleProvenance,
    BattleSpeciesDefinition,
    DeterminantValues,
    RivalStarterDefinition,
)
from backend.app.models.story import StoryDefinition

from .battle_text import battle_text
from .parsers import ParseError, assert_source_patterns, parse_rgbds_constants, require_constants
from .parsers.battle import (
    parse_battle_moves,
    parse_first_rival_parties,
    parse_starter_base,
    parse_stat_ratios,
    source_lines,
    validate_level_five_learnset,
)

REPOSITORY = "https://github.com/pret/pokered"


def build_first_battle(root: Path, revision: str, story: StoryDefinition) -> BattleDefinition:
    def read(file: str) -> str:
        return (root / file).read_text(encoding="utf-8")

    def provenance(file: str, symbol: str) -> BattleProvenance:
        return BattleProvenance(repository=REPOSITORY, revision=revision, file=file, symbol=symbol)

    _validate_rules(read)
    growth_rows = re.findall(r"^\s*growth_rate\s+([^;\n]+)", read("data/growth_rates.asm"), re.M)
    if len(growth_rows) != 6:
        raise ParseError("unsupported growth-rate table shape")
    coefficients = tuple(int(value.strip()) for value in growth_rows[3].split(","))
    if coefficients != (6, 5, -15, 100, 140):
        raise ParseError("unsupported medium-slow growth coefficients")
    money_constants = parse_rgbds_constants(read("engine/movie/oak_speech/init_player_data.asm"))
    start_money = require_constants(money_constants, {"START_MONEY"})["START_MONEY"]
    # START_MONEY is written as HIGH in the middle byte and zero in the other
    # two BCD bytes. Trainer information copies just the first two BCD3 bytes.
    starting_money = int(f"{start_money >> 8:02x}") * 100
    match = re.search(
        r"pic_money\s+Rival1Pic,\s*(\d+)", read("data/trainers/pic_pointers_money.asm")
    )
    if match is None:
        raise ParseError("missing RIVAL1 money record")
    trainer_base_money = int(f"{int(match[1]):06d}"[:4])
    move_file = "data/moves/moves.asm"
    moves = parse_battle_moves(
        read(move_file),
        parse_rgbds_constants(read("constants/move_constants.asm")),
        provenance(move_file, "Moves"),
    )
    display_names = re.findall(r'^\s*li "([^"]+)"', read("data/moves/names.asm"), re.M)
    if len(display_names) != max(move.id for move in moves):
        raise ParseError("unsupported move-name table length")
    supported_moves = {move.constant for move in moves}
    expected_effects = {
        "TACKLE": "damage",
        "SCRATCH": "damage",
        "GROWL": "attack_down",
        "TAIL_WHIP": "defense_down",
        "STRUGGLE": "recoil",
    }
    for move in moves:
        if move.type != "NORMAL" or move.effect != expected_effects[move.constant]:
            raise ParseError(f"unsupported first-battle move behavior: {move.constant}")
        if (move.power == 0) != (move.effect in {"attack_down", "defense_down"}):
            raise ParseError(f"unsupported first-battle move power: {move.constant}")
    species = []
    learnsets = read("data/pokemon/evos_moves.asm")
    for starter in story.starters.values():
        name = starter.species.constant
        file = f"data/pokemon/base_stats/{name.lower()}.asm"
        stats, types, starting_moves, experience, growth = parse_starter_base(read(file))
        if growth != "GROWTH_MEDIUM_SLOW":
            raise ParseError(f"unsupported starter growth: {name}")
        if not set(starting_moves) <= supported_moves or not set(types) <= {
            "FIRE",
            "WATER",
            "GRASS",
            "POISON",
        }:
            raise ParseError(f"unsupported first-battle types or starting moves: {name}")
        if starting_moves[0] not in {"TACKLE", "SCRATCH"} or starting_moves[1] not in {
            "GROWL",
            "TAIL_WHIP",
        }:
            raise ParseError(f"unsupported starting move slots: {name}")
        validate_level_five_learnset(learnsets, f"{name.title()}EvosMoves")
        species.append(
            BattleSpeciesDefinition(
                species=starter.species,
                base_stats=stats,
                types=types,
                starting_moves=starting_moves,
                base_experience=experience,
                growth_rate=growth,
                provenance=(
                    provenance(file, name),
                    provenance("data/pokemon/evos_moves.asm", f"{name.title()}EvosMoves"),
                ),
            )
        )
    parties = parse_first_rival_parties(read("data/trainers/parties.asm"))
    rival_starters = []
    for starter in story.starters.values():
        rival = starter.rival_species.constant
        if parties.count(rival) != 1:
            raise ParseError(f"unsupported rival party mapping: {rival}")
        rival_starters.append(
            RivalStarterDefinition(
                player_species=starter.species.constant,
                rival_species=rival,
                trainer_party=parties.index(rival) + 1,
            )
        )
    if parties != ("SQUIRTLE", "BULBASAUR", "CHARMANDER"):
        raise ParseError("first rival party order drift")
    dvs = require_constants(
        parse_rgbds_constants(read("constants/battle_constants.asm")),
        {"ATKDEFDV_TRAINER", "SPDSPCDV_TRAINER", "MAX_STAT_VALUE"},
    )
    if dvs["MAX_STAT_VALUE"] != 999:
        raise ParseError("unsupported maximum stat value")
    return BattleDefinition(
        growth_coefficients=(6, 5, -15, 100, 140),
        starting_money=starting_money,
        trainer_base_money=trainer_base_money,
        move_names=tuple(
            (
                move.constant,
                display_names[move.id - 1],
            )
            for move in moves
        ),
        text_templates=tuple(
            (symbol, battle_text(read(file), symbol))
            for file, symbols in (
                (
                    "data/text/text_2.asm",
                    (
                        "_AttackMissedText",
                        "_CriticalHitText",
                        "_EnemyMonFaintedText",
                        "_PlayerMonFaintedText",
                        "_TrainerWantsToFightText",
                        "_TrainerSentOutText",
                        "_GoText",
                        "_UsedMove1Text",
                        "_MoveNameText",
                        "_EndUsedMove1Text",
                        "_GainedText",
                        "_ExpPointsText",
                        "_GrewLevelText",
                        "_TrainerDefeatedText",
                        "_MoneyForWinningText",
                        "_Rival1WinText",
                    ),
                ),
                ("text/OaksLab.asm", ("_OaksLabRivalIPickedTheWrongPokemonText",)),
                (
                    "data/text/text_3.asm",
                    ("_HitWithRecoilText", "_MonsStatsFellText", "_FellText", "_ButItFailedText"),
                ),
            )
            for symbol in symbols
        ),
        species=tuple(species),
        moves=moves,
        rival_starters=tuple(rival_starters),
        rival_dvs=DeterminantValues(
            attack_defense=dvs["ATKDEFDV_TRAINER"], speed_special=dvs["SPDSPCDV_TRAINER"]
        ),
        stat_ratios=parse_stat_ratios(read("data/battle/stat_modifiers.asm")),
        provenance=tuple(
            provenance(file, symbol)
            for file, symbol in (
                ("engine/battle/core.asm", "MainInBattleLoop"),
                ("engine/battle/effects.asm", "StatModifierDownEffect"),
                ("data/moves/names.asm", "MoveNames"),
                ("data/text/text_2.asm", "_TrainerWantsToFightText"),
                ("data/text/text_3.asm", "_MonsStatsFellText"),
                ("home/move_mon.asm", "CalcStat"),
                ("engine/pokemon/add_mon.asm", "_AddPartyMon"),
                ("engine/battle/trainer_ai.asm", "TrainerAI"),
                ("engine/battle/move_effects/recoil.asm", "RecoilEffect_"),
                ("data/trainers/parties.asm", "Rival1Data"),
                ("constants/battle_constants.asm", "ATKDEFDV_TRAINER"),
                ("data/battle/stat_modifiers.asm", "StatModifierRatios"),
                ("engine/battle/experience.asm", "GainExperience"),
                ("engine/pokemon/experience.asm", "CalcExperience"),
                ("data/growth_rates.asm", "GrowthRateTable"),
                ("home/trainers2.asm", "GetTrainerInformation"),
                ("data/trainers/pic_pointers_money.asm", "TrainerPicAndMoneyPointers"),
                ("engine/battle/read_trainer_party.asm", "ReadTrainerParty"),
                ("engine/movie/oak_speech/init_player_data.asm", "InitPlayerData"),
                ("text/OaksLab.asm", "_OaksLabRivalIPickedTheWrongPokemonText"),
                ("engine/events/heal_party.asm", "HealParty"),
            )
        ),
    )


def _validate_rules(read: Callable[[str], str]) -> None:
    # Data is parsed; these guards tie hand-translated executable semantics to
    # their source routines. The checkout also has revision/tree integrity checks.
    trainer_classes = [
        line.split()[1]
        for line in source_lines(read("constants/trainer_constants.asm"))
        if line.startswith("trainer_const ")
    ]
    rival_index = trainer_classes.index("RIVAL1") - 1
    for file, prefix, expected in (
        ("data/trainers/move_choices.asm", "move_choices", "move_choices 1"),
        ("data/trainers/ai_pointers.asm", "dbw", "dbw 3, GenericAI"),
    ):
        rows = [line for line in source_lines(read(file)) if line.startswith(prefix)]
        if len(rows) <= rival_index or rows[rival_index] != expected:
            raise ParseError(f"{file} source drift: unsupported RIVAL1 AI")
    checks = {
        "macros/data.asm": {"accuracy percent macro": r'DEF percent EQUS "\* \$ff / 100"'},
        "engine/pokemon/add_mon.asm": {
            "player DV draw order": r"call Random\nld b, a\ncall Random",
            "player DV write order": r"ld \[hli\], a\nld \[hl\], b",
        },
        "engine/battle/core.asm": {
            "lab loss bypasses blackout": (
                r"(?s)HandlePlayerBlackOut:.*?cp OPP_RIVAL1.*?"
                r"ld hl, Rival1WinText\ncall PrintText\n"
                r"ld a, \[wCurMap\]\ncp OAKS_LAB\nret z"
            ),
            "survivor precedes enemy faint text": (
                r"(?s)\.playermonnotfaint\ncall AnyPartyAlive\nld a, d\nand a\nret z\n"
                r"ld hl, EnemyMonFaintedText\ncall PrintText"
            ),
            "victory text and payment order": (
                r"(?s)TrainerBattleVictory:.*?ld hl, TrainerDefeatedText\ncall PrintText"
                r".*?call PrintEndBattleText\nld hl, MoneyForWinningText\ncall PrintText"
                r".*?predef_jump AddBCDPredef"
            ),
            "rival slot weights": (
                r"(?s)SelectEnemyMove:.*?cp 25 percent\n.*?cp 50 percent\n"
                r".*?cp 75 percent - 1"
            ),
            "speed tie": r"(?s)\.speedEqual.*?call BattleRandom\ncp 50 percent \+ 1",
            "critical rotate": r"call BattleRandom\nrlc a\nrlc a\nrlc a\ncp b",
            "damage random rejection": r"call BattleRandom\nrrca\ncp 85 percent \+ 1\njr c, \.loop",
            "damage before accuracy": r"call RandomizeDamage\n\.moveHitTest\ncall MoveHitTest",
            "accuracy comparison": (
                r"\.doAccuracyCheck\ncall BattleRandom\ncp b\njr nc, \.moveMissed"
            ),
            "trainer DVs": r"ld a, ATKDEFDV_TRAINER\nld b, SPDSPCDV_TRAINER",
            "party exhaustion before victory": (
                r"(?s)HandleEnemyMonFainted:.*?call FaintEnemyPokemon\ncall AnyPartyAlive\n"
                r"ld a, d\nand a\njp z, HandlePlayerBlackOut.*?jp z, TrainerBattleVictory"
            ),
            "critical unmodified stats": (
                r"(?s)GetDamageVarsForPlayerAttack:.*?call GetEnemyMonStat"
                r".*?ld hl, wPartyMon1Attack"
            ),
        },
        "engine/battle/effects.asm": {
            "rival stat failure": r"call BattleRandom\ncp 25 percent \+ 1\njp c, MoveMissed",
            "stat down floor": r"dec b\njp z, CantLowerAnymore",
        },
        "engine/battle/trainer_ai.asm": {
            "trainer action draw": r"call Random\njp hl",
            "generic AI": r"GenericAI:\nand a\nret",
        },
        "scripts/OaksLab.asm": {
            "rival team branch": (
                r"(?s)OaksLabRivalStartBattleScript:.*?cp STARTER2\n.*?ld a, \$1\n"
                r".*?cp STARTER3\n.*?ld a, \$2\n.*?ld a, \$3\n"
                r"\.done\nld \[wTrainerNo\], a"
            )
        },
        "engine/battle/decrement_pp.asm": {"Struggle skips PP": r"cp STRUGGLE\nret z"},
        "engine/battle/experience.asm": {
            "trainer boost after base division": (
                r"(?s)ld a, 7\nldh \[hDivisor\], a\nld b, 4\ncall Divide"
                r".*?ld a, \[wIsInBattle\]\ndec a\ncall nz, BoostExp"
            ),
            "stat experience saturation": (
                r"(?s)\.maxStatExp\nld a, \$ff\nld \[de\], a\ninc de\nld \[de\], a"
            ),
            "trainer boost integer half": r"srl b\nrr c\nadd c",
            "level-up current HP adjustment": (
                r"(?s)call CalcStats.*?add c\nld \[hld\], a\nld a, \[hl\]\nadc b"
            ),
        },
        "home/move_mon.asm": {
            "stat experience square-root cap": r"inc b\nld a, b\ncp \$ff\njr z, \.statExpDone",
            "stat experience divisor": r"srl b\nsrl b",
            "stat experience ceiling root": r"sbc d\njr c, \.statExpLoop",
            "stat level divisor and constant": (
                r"(?s)ld a, \$64\nldh \[hDivisor\], a.*?call Divide\n"
                r"ld a, c\ncp \$1\nld a, 5.*?ld a, 10\n\.notHPStat"
            ),
            "stat cap": (
                r"\.overflow\nld a, HIGH\(MAX_STAT_VALUE\)\nldh \[hMultiplicand\+1\], a\n"
                r"ld a, LOW\(MAX_STAT_VALUE\)\nldh \[hMultiplicand\+2\], a"
            ),
        },
        "engine/pokemon/experience.asm": {
            "growth table fractional cube": (
                r"(?s)CalcExperience::.*?ld hl, GrowthRateTable.*?call CalcDSquared"
                r".*?and \$f0\nswap a.*?and \$f\nldh \[hDivisor\], a\nld b, \$4\ncall Divide"
            ),
            "growth squared sign": r"and \$80\njr nz, \.subtractSquaredTerm",
        },
        "engine/events/heal_party.asm": {
            "heal status": r"ld hl, MON_STATUS - MON_HP\nadd hl, de\nxor a\nld \[hl\], a",
            "heal PP": r"(?s)ld a, \[wMoveData \+ MOVE_PP\].*?and PP_UP_MASK\nadd b\nld \[hl\], a",
            "heal HP": (
                r"ld hl, MON_MAXHP - MON_HP\nadd hl, de\nld a, \[hli\]\n"
                r"ld \[de\], a\ninc de\nld a, \[hl\]\nld \[de\], a"
            ),
        },
        "home/trainers2.asm": {
            "two BCD base-money bytes": (
                r"ld de, wTrainerBaseMoney\nld a, \[hli\]\nld \[de\], a\ninc de\n"
                r"ld a, \[hli\]\nld \[de\], a\njp BankswitchBack"
            ),
        },
        "data/trainers/pic_pointers_money.asm": {
            "three-byte BCD money macro": r"MACRO pic_money\ndw \\1\nbcd3 \\2\nENDM",
        },
        "engine/battle/read_trainer_party.asm": {
            "reward uses final enemy level": (
                r"(?s)\.FinishUp.*?ld a, \[wCurEnemyLevel\]\nld b, a\n\.LastLoop\n"
                r"ld hl, wTrainerBaseMoney \+ 1\nld c, 2.*?predef AddBCDPredef"
                r".*?dec b\njr nz, \.LastLoop"
            ),
        },
        "engine/movie/oak_speech/init_player_data.asm": {
            "starting BCD wallet": (
                r"ld hl, wPlayerMoney \+ 1\nld a, HIGH\(START_MONEY\)\nld \[hld\], a\n"
                r"xor a\nld \[hli\], a\ninc hl\nld \[hl\], a"
            ),
        },
        "engine/battle/move_effects/recoil.asm": {
            "Struggle half recoil": r"srl b\nrr c\nld a, d\ncp STRUGGLE\njr z, \.gotRecoilDamage"
        },
    }
    for file, patterns in checks.items():
        assert_source_patterns("\n".join(source_lines(read(file))), patterns, file)
