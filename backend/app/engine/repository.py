from __future__ import annotations

import os
from pathlib import Path

from backend.app.models.map import WorldDefinition


def default_data_path() -> Path:
    configured = os.environ.get("POKEMON_DATA_PATH")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[3] / "data" / "generated" / "json" / "world.json"


def load_world(path: Path | None = None) -> WorldDefinition:
    data_path = path or default_data_path()
    try:
        content = data_path.read_text(encoding="utf-8")
    except OSError as error:
        raise RuntimeError(f"unable to read compiled game data at {data_path}") from error
    return WorldDefinition.model_validate_json(content)
