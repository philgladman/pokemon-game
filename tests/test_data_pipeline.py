from pathlib import Path

import pytest
import yaml

from backend.app.models.map import WorldDefinition
from tools.compile_data import CompileError, compile_world
from tools.pokered_importer import importer
from tools.yaml_loader import load_yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
IMPORTED = PROJECT_ROOT / "data/yaml/imported/pallet_town.yaml"
OVERLAY = PROJECT_ROOT / "data/yaml/world.yaml"


def test_checked_in_yaml_compiles_to_valid_world() -> None:
    world = compile_world(IMPORTED, OVERLAY)

    assert isinstance(world, WorldDefinition)
    assert world.start_map == "pallet_town"
    assert (world.maps["pallet_town"].width, world.maps["pallet_town"].height) == (20, 18)
    assert world.maps["pallet_town"].source.revision == "af519899719f0754965776faac0e836a3b906e6d"


def test_visual_overlay_cannot_change_source_collision(tmp_path: Path) -> None:
    overlay = yaml.safe_load(OVERLAY.read_text(encoding="utf-8"))
    overlay["maps"][0]["visual_overrides"].append(
        {"position": {"x": 5, "y": 6}, "tile": "building"}
    )
    invalid_overlay = tmp_path / "world.yaml"
    invalid_overlay.write_text(yaml.safe_dump(overlay), encoding="utf-8")

    with pytest.raises(CompileError, match="changes source collision"):
        compile_world(IMPORTED, invalid_overlay)


def test_importer_fails_loudly_on_unknown_object_syntax() -> None:
    malformed = "const_export PERSON\nobject_event 1, 2, SPRITE_GIRL\n"

    with pytest.raises(importer.ImporterError, match="unsupported object_event"):
        importer._parse_objects(malformed)


def test_importer_expands_source_blocks_to_logical_collision_tiles() -> None:
    blockset = bytes(range(16))

    assert importer._expand_collision_tiles([[0]], blockset) == [[4, 6], [12, 14]]


def test_yaml_loader_rejects_duplicate_keys(tmp_path: Path) -> None:
    duplicate_yaml = tmp_path / "duplicate.yaml"
    duplicate_yaml.write_text("width: 10\nwidth: 12\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="duplicate key 'width'"):
        load_yaml(duplicate_yaml)


def test_compiler_derives_warp_destinations_from_source_indices() -> None:
    world = compile_world(IMPORTED, OVERLAY)

    entry = world.maps["pallet_town"].transitions[0]
    assert entry.target_map == "reds_house_1f"
    assert entry.target_position.model_dump() == {"x": 2, "y": 7}

    exit_transition = world.maps["reds_house_1f"].transitions[0]
    assert exit_transition.target_map == "pallet_town"
    assert exit_transition.target_position.model_dump() == {"x": 5, "y": 5}


def test_compiler_rejects_missing_source_destination_warp(tmp_path: Path) -> None:
    imported = yaml.safe_load(IMPORTED.read_text(encoding="utf-8"))
    imported["maps"][0]["warps"][0]["target_warp"] = 99
    invalid_import = tmp_path / "imported.yaml"
    invalid_import.write_text(yaml.safe_dump(imported, sort_keys=False), encoding="utf-8")

    with pytest.raises(CompileError, match="targets missing warp 99"):
        compile_world(invalid_import, OVERLAY)


def test_last_map_transition_requires_explicit_context(tmp_path: Path) -> None:
    overlay = yaml.safe_load(OVERLAY.read_text(encoding="utf-8"))
    del overlay["maps"][1]["transitions"][0]["last_map_context"]
    invalid_overlay = tmp_path / "world.yaml"
    invalid_overlay.write_text(yaml.safe_dump(overlay, sort_keys=False), encoding="utf-8")

    with pytest.raises(CompileError, match="requires last_map_context"):
        compile_world(IMPORTED, invalid_overlay)
