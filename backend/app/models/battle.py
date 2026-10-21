"""The deliberately narrow, immutable first-rival-battle domain.

These models are independent of the browser protocol and overworld party state.
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from .common import StrictModel
from .map import SourceProvenance
from .pokemon import SpeciesDefinition

Side = Literal["player", "rival"]
BattleOutcome = Literal["ongoing", "player_win", "player_loss"]
MoveEffect = Literal["damage", "attack_down", "defense_down", "recoil"]


class FrozenBattleModel(StrictModel):
    model_config = ConfigDict(frozen=True)


class BattleProvenance(SourceProvenance):
    model_config = ConfigDict(frozen=True)


class PokemonStats(FrozenBattleModel):
    hp: int = Field(ge=1, le=999)
    attack: int = Field(ge=1, le=999)
    defense: int = Field(ge=1, le=999)
    speed: int = Field(ge=1, le=999)
    special: int = Field(ge=1, le=999)


class StatExperience(FrozenBattleModel):
    hp: int = Field(default=0, ge=0, le=65535)
    attack: int = Field(default=0, ge=0, le=65535)
    defense: int = Field(default=0, ge=0, le=65535)
    speed: int = Field(default=0, ge=0, le=65535)
    special: int = Field(default=0, ge=0, le=65535)


class DeterminantValues(FrozenBattleModel):
    attack_defense: int = Field(ge=0, le=255)
    speed_special: int = Field(ge=0, le=255)

    @property
    def hp(self) -> int:
        return (
            ((self.attack_defense >> 4) & 1) * 8
            + (self.attack_defense & 1) * 4
            + ((self.speed_special >> 4) & 1) * 2
            + (self.speed_special & 1)
        )


class BattleSpeciesDefinition(FrozenBattleModel):
    species: SpeciesDefinition
    base_stats: PokemonStats
    types: tuple[str, str]
    starting_moves: tuple[str, ...] = Field(min_length=1, max_length=4)
    base_experience: int = Field(ge=0, le=255)
    growth_rate: str
    provenance: tuple[BattleProvenance, ...]


class MoveDefinition(FrozenBattleModel):
    id: int = Field(ge=1, le=255)
    constant: str
    effect: MoveEffect
    power: int = Field(ge=0, le=255)
    type: str
    accuracy: int = Field(ge=1, le=255)
    pp: int = Field(ge=1, le=40)
    provenance: BattleProvenance


class RivalStarterDefinition(FrozenBattleModel):
    player_species: str
    rival_species: str
    trainer_party: int = Field(ge=1, le=3)
    level: Literal[5] = 5


class BattleDefinition(FrozenBattleModel):
    growth_coefficients: tuple[int, int, int, int, int] = (6, 5, -15, 100, 140)
    starting_money: int = Field(default=3000, ge=0, le=999999)
    trainer_base_money: int = Field(default=35, ge=0)
    move_names: tuple[tuple[str, str], ...] = ()
    text_templates: tuple[tuple[str, str], ...] = ()
    species: tuple[BattleSpeciesDefinition, ...]
    moves: tuple[MoveDefinition, ...]
    rival_starters: tuple[RivalStarterDefinition, ...]
    rival_dvs: DeterminantValues
    stat_ratios: tuple[tuple[int, int], ...] = Field(min_length=13, max_length=13)
    provenance: tuple[BattleProvenance, ...]

    def species_named(self, constant: str) -> BattleSpeciesDefinition:
        for item in self.species:
            if item.species.constant == constant:
                return item
        raise ValueError(f"unsupported first-battle species: {constant}")

    def move_named(self, constant: str) -> MoveDefinition:
        for item in self.moves:
            if item.constant == constant:
                return item
        raise ValueError(f"unsupported first-battle move: {constant}")

    def rival_for(self, constant: str) -> RivalStarterDefinition:
        for item in self.rival_starters:
            if item.player_species == constant:
                return item
        raise ValueError(f"unsupported first-battle starter: {constant}")


class BattleMove(FrozenBattleModel):
    constant: str
    pp: int = Field(ge=0, le=40)


class BattlePokemon(FrozenBattleModel):
    species: str
    level: int = Field(default=5, ge=5, le=6)
    experience: int = Field(default=135, ge=0, le=0xFFFFFF)
    stat_experience: StatExperience = StatExperience()
    dvs: DeterminantValues
    stats: PokemonStats
    hp: int = Field(ge=0, le=999)
    moves: tuple[BattleMove, ...] = Field(min_length=1, max_length=4)
    attack_stage: int = Field(default=0, ge=-6, le=0)
    defense_stage: int = Field(default=0, ge=-6, le=0)

    @model_validator(mode="after")
    def hp_is_bounded(self) -> BattlePokemon:
        if self.hp > self.stats.hp:
            raise ValueError("current HP exceeds maximum HP")
        return self


class BattleState(FrozenBattleModel):
    player: BattlePokemon
    rival: BattlePokemon
    turn: int = Field(default=0, ge=0)
    outcome: BattleOutcome = "ongoing"

    @model_validator(mode="after")
    def outcome_matches_hp(self) -> BattleState:
        if self.outcome == "ongoing" and (not self.player.hp or not self.rival.hp):
            raise ValueError("ongoing battles require two conscious Pokémon")
        if self.outcome == "player_win" and (self.rival.hp or not self.player.hp):
            raise ValueError("a win requires a conscious player and fainted rival")
        if self.outcome == "player_loss" and self.player.hp:
            raise ValueError("a loss requires a fainted player")
        return self


class MoveCommand(FrozenBattleModel):
    """Zero-based move slot; None requests Struggle when every move has zero PP."""

    slot: int | None = Field(default=None, ge=0, le=3)


class BattleEvent(FrozenBattleModel):
    type: Literal["move", "miss", "damage", "stat_down", "stat_failed", "recoil", "faint"]
    side: Side
    move: str
    amount: int = Field(default=0, ge=0)
    critical: bool = False


class TurnResult(FrozenBattleModel):
    state: BattleState
    events: tuple[BattleEvent, ...]
