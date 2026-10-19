from pathlib import Path

import pytest

from backend.app.presentation.three_d import ThreeDConfigError, load_three_d_manifest


def test_three_d_manifest_preserves_glb_fallback_configuration(tmp_path: Path) -> None:
    path = tmp_path / "three_d.json"
    path.write_text(
        """
        {
          "appearances": [{
            "id": "tile.tree",
            "source": {
              "type": "gltf",
              "url": "/assets/models/tree.glb",
              "fallback": {
                "type": "primitive",
                "shape": "tree",
                "color": "#286548"
              }
            }
          }]
        }
        """,
        encoding="utf-8",
    )

    manifest = load_three_d_manifest(path).as_registry()

    assert manifest["tile.tree"].source.type == "gltf"
    assert manifest["tile.tree"].source.fallback.shape == "tree"  # type: ignore[union-attr]


def test_three_d_manifest_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    path = tmp_path / "three_d.json"
    path.write_text('{"appearances": [], "appearances": []}', encoding="utf-8")

    with pytest.raises(ThreeDConfigError, match="duplicate JSON key"):
        load_three_d_manifest(path)
