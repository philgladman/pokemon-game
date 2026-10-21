"""Authoritative presentation data; browser renderers never calculate battle state."""

from .battle import BattleOutcome, PokemonStats, StatExperience
from .common import StrictModel


class BattleMoveView(StrictModel):
    slot: int
    name: str
    pp: int
    max_pp: int


class BattlePokemonView(StrictModel):
    species: str
    name: str
    level: int
    hp: int
    max_hp: int
    image_url: str
    moves: list[BattleMoveView]
    stats: PokemonStats
    experience: int
    stat_experience: StatExperience


class BattleFrame(StrictModel):
    text: str
    player_hp: int
    rival_hp: int
    player_pp: list[int]
    player_level: int
    player_max_hp: int
    player_stats: PokemonStats
    rival_level: int
    rival_max_hp: int
    rival_stats: PokemonStats
    show_stats: bool = False


class BattleBatch(StrictModel):
    id: str
    frames: list[BattleFrame]


class BattleSnapshot(StrictModel):
    id: str
    turn: int
    outcome: BattleOutcome
    player: BattlePokemonView
    rival: BattlePokemonView
    action_token: str | None
    batch: BattleBatch | None
