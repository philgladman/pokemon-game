from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from backend.app.models.rendering import ThreeDManifest


class ThreeDConfigError(RuntimeError):
    """Raised when the project-owned 3D appearance manifest is invalid."""


def default_manifest_path() -> Path:
    configured = os.environ.get("POKEMON_THREE_D_CONFIG")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[3] / "data" / "config" / "three_d.json"


def load_three_d_manifest(path: Path | None = None) -> ThreeDManifest:
    manifest_path = path or default_manifest_path()
    try:
        raw = json.loads(
            manifest_path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
        )
        return ThreeDManifest.model_validate(raw)
    except OSError as error:
        raise ThreeDConfigError(f"unable to read 3D manifest: {manifest_path}") from error
    except (json.JSONDecodeError, ValidationError, ValueError) as error:
        raise ThreeDConfigError(f"invalid 3D manifest {manifest_path}: {error}") from error


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result
