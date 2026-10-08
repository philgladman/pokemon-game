from pathlib import Path

import pytest

from backend.app.engine.repository import load_world
from backend.app.models.map import WorldDefinition

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def world() -> WorldDefinition:
    return load_world(PROJECT_ROOT / "data/generated/json/world.json")
