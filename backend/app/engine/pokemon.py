"""Fresh level-five Pokémon, as created by AddPartyMon and LoadEnemyMonData."""

from __future__ import annotations

from collections.abc import Callable
from math import isqrt

from backend.app.models.battle import (
    BattleDefinition,
    BattleMove,
    BattlePokemon,
    BattleSpeciesDefinition,
    BattleState,
    DeterminantValues,
    PokemonStats,
    StatExperience,
)

ByteRng = Callable[[], int]


def random_byte(rng: ByteRng) -> int:
    value = rng()
    if type(value) is not int or not 0 <= value <= 255:
        raise ValueError("battle RNG must return an integer byte")
    return value


def calculate_starter_stats(
    definition: BattleSpeciesDefinition,
    dvs: DeterminantValues,
    level: int = 5,
    stat_experience: StatExperience | None = None,
) -> PokemonStats:
    """Gen 1 CalcStat, including its capped ceiling square-root stat bonus."""
    stat_experience = stat_experience or StatExperience()

    def stat(name: str, dv: int, bonus: int = 5) -> int:
        experience = int(getattr(stat_experience, name))
        root = isqrt(experience)
        root += root * root < experience
        base = int(getattr(definition.base_stats, name))
        return min(999, (2 * (base + dv) + min(255, root) // 4) * level // 100 + bonus)

    return PokemonStats(
        hp=stat("hp", dvs.hp, level + 10),
        attack=stat("attack", dvs.attack_defense >> 4),
        defense=stat("defense", dvs.attack_defense & 15),
        speed=stat("speed", dvs.speed_special >> 4),
        special=stat("special", dvs.speed_special & 15),
    )


def realize_starter(
    definition: BattleDefinition, species: str, dvs: DeterminantValues
) -> BattlePokemon:
    data = definition.species_named(species)
    stats = calculate_starter_stats(data, dvs)
    return BattlePokemon(
        species=species,
        experience=experience_at_level(definition, 5),
        dvs=dvs,
        stats=stats,
        hp=stats.hp,
        moves=tuple(
            BattleMove(constant=name, pp=definition.move_named(name).pp)
            for name in data.starting_moves
        ),
    )


def experience_at_level(definition: BattleDefinition, level: int) -> int:
    numerator, denominator, square, linear, constant = definition.growth_coefficients
    return max(
        0, numerator * level**3 // denominator + square * level**2 + linear * level - constant
    )


def award_battle_experience(definition: BattleDefinition, state: BattleState) -> BattleState:
    """GainExperience for the one surviving original-trainer participant."""
    if state.outcome != "player_win":
        return state
    player = state.player
    foe = definition.species_named(state.rival.species)
    gained = foe.base_experience * state.rival.level // 7
    experience = player.experience + gained + gained // 2
    stat_experience = StatExperience(
        **{
            name: min(65535, getattr(player.stat_experience, name) + getattr(foe.base_stats, name))
            for name in StatExperience.model_fields
        }
    )
    level = player.level
    if experience >= experience_at_level(definition, 6):
        level = 6
    stats = (
        calculate_starter_stats(
            definition.species_named(player.species), player.dvs, level, stat_experience
        )
        if level != player.level
        else player.stats
    )
    player = player.model_copy(
        update={
            "experience": experience,
            "stat_experience": stat_experience,
            "level": level,
            "stats": stats,
            "hp": player.hp + stats.hp - player.stats.hp,
        }
    )
    return state.model_copy(update={"player": player})


def generate_player_starter(
    definition: BattleDefinition, species: str, rng: ByteRng
) -> BattlePokemon:
    definition.species_named(species)  # Reject unsupported input before consuming randomness.
    speed_special = random_byte(rng)
    attack_defense = random_byte(rng)
    return realize_starter(
        definition,
        species,
        DeterminantValues(
            attack_defense=attack_defense,
            speed_special=speed_special,
        ),
    )


def create_rival_battle(definition: BattleDefinition, player: BattlePokemon) -> BattleState:
    """Accept a previously realized player; never reroll their DVs at battle entry."""
    rival = definition.rival_for(player.species)
    expected = realize_starter(definition, player.species, player.dvs)
    if player != expected:
        raise ValueError("first rival battle requires a fresh, healthy player starter")
    return BattleState(
        player=player,
        rival=realize_starter(
            definition,
            rival.rival_species,
            definition.rival_dvs,
        ),
    )
