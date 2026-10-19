from __future__ import annotations

import os
from pathlib import Path

from backend.app.models.map import WorldDefinition
from backend.app.source.pokered import PokeredSource
from backend.app.source.provider import GameSource


def default_source_root() -> Path:
    configured = os.environ.get("POKERED_SOURCE_ROOT")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[3] / "external" / "pokered"


def default_source() -> PokeredSource:
    return PokeredSource(
        default_source_root(),
        player_name=os.environ.get("POKEMON_PLAYER_NAME", "RED"),
        rival_name=os.environ.get("POKEMON_RIVAL_NAME", "BLUE"),
    )


def load_world(source: GameSource | None = None) -> WorldDefinition:
    return (source or default_source()).build_world()
