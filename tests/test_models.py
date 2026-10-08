import pytest
from pydantic import ValidationError

from backend.app.models.assets import AppearanceDefinition, PrimitiveAsset
from backend.app.models.common import Direction, Position
from backend.app.models.map import (
    MapDefinition,
    SourceReference,
    TileDefinition,
    TransitionDefinition,
    WorldDefinition,
)

SOURCE = SourceReference(
    repository="https://example.invalid/source",
    revision="a" * 40,
    map_name="Fixture",
)
FLOOR = TileDefinition(
    id="floor",
    walkable=True,
    appearance="tile.floor",
)
WALL = TileDefinition(
    id="wall",
    walkable=False,
    appearance="tile.wall",
)
ASSETS = {
    "character.player": AppearanceDefinition(
        id="character.player",
        source=PrimitiveAsset(shape="capsule", color="#ffff00"),
    ),
    "tile.floor": AppearanceDefinition(
        id="tile.floor",
        source=PrimitiveAsset(shape="flat", color="#ffffff"),
    ),
    "tile.wall": AppearanceDefinition(
        id="tile.wall",
        source=PrimitiveAsset(shape="box", color="#000000"),
    ),
}


def make_map(**updates: object) -> MapDefinition:
    values: dict[str, object] = {
        "id": "room",
        "name": "Room",
        "width": 2,
        "height": 2,
        "tiles": [["floor", "wall"], ["floor", "floor"]],
        "tile_definitions": {"floor": FLOOR, "wall": WALL},
        "player_spawn": Position(x=0, y=0),
        "source": SOURCE,
    }
    values.update(updates)
    return MapDefinition.model_validate(values)


def test_map_rejects_malformed_dimensions() -> None:
    with pytest.raises(ValidationError, match="exactly 2 entries"):
        make_map(tiles=[["floor"], ["floor", "floor"]])


def test_map_rejects_unknown_tile_reference() -> None:
    with pytest.raises(ValidationError, match="unknown tiles"):
        make_map(tiles=[["floor", "missing"], ["floor", "floor"]])


def test_map_rejects_blocked_spawn() -> None:
    with pytest.raises(ValidationError, match="spawn must be on a walkable"):
        make_map(player_spawn=Position(x=1, y=0))


def test_world_rejects_unknown_transition_target() -> None:
    room = make_map(
        transitions=[
            TransitionDefinition(
                position=Position(x=0, y=1),
                target_map="missing",
                target_position=Position(x=0, y=0),
                target_facing=Direction.NORTH,
            )
        ]
    )
    with pytest.raises(ValidationError, match="targets unknown map"):
        WorldDefinition(
            start_map="room",
            player_appearance="character.player",
            asset_manifest=ASSETS,
            maps={"room": room},
        )


def test_world_rejects_unknown_appearance_reference() -> None:
    unknown_floor = FLOOR.model_copy(update={"appearance": "tile.missing"})
    room = make_map(tile_definitions={"floor": unknown_floor, "wall": WALL})

    with pytest.raises(ValidationError, match="unknown appearance"):
        WorldDefinition(
            start_map="room",
            player_appearance="character.player",
            asset_manifest=ASSETS,
            maps={"room": room},
        )


def test_world_rejects_npc_overlapping_transition_source(world: WorldDefinition) -> None:
    payload = world.model_dump(mode="json")
    town = payload["maps"]["pallet_town"]
    town["npcs"][0]["position"] = town["transitions"][0]["position"]

    with pytest.raises(
        ValidationError,
        match=r"transition at \(5, 5\) overlaps NPC 'town_gardener' and is unreachable",
    ):
        WorldDefinition.model_validate(payload)


def test_map_rejects_tile_definition_key_id_mismatch() -> None:
    with pytest.raises(
        ValidationError,
        match="tile definition key 'ground' does not match id 'floor' in map 'room'",
    ):
        make_map(
            tiles=[["ground", "wall"], ["ground", "ground"]],
            tile_definitions={"ground": FLOOR, "wall": WALL},
        )


def test_world_rejects_asset_manifest_key_id_mismatch(world: WorldDefinition) -> None:
    payload = world.model_dump(mode="json")
    payload["asset_manifest"]["character.player"]["id"] = "character.impostor"

    with pytest.raises(
        ValidationError,
        match=r"asset manifest key 'character\.player' does not match id 'character\.impostor'",
    ):
        WorldDefinition.model_validate(payload)


def test_world_rejects_map_key_id_mismatch(world: WorldDefinition) -> None:
    payload = world.model_dump(mode="json")
    payload["maps"]["pallet_town"]["id"] = "renamed_town"

    with pytest.raises(
        ValidationError,
        match="map key 'pallet_town' does not match id 'renamed_town'",
    ):
        WorldDefinition.model_validate(payload)


def test_extra_schema_fields_fail_immediately() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        Position.model_validate({"x": 0, "y": 0, "z": 0})


def test_strict_models_reject_string_coercion() -> None:
    with pytest.raises(ValidationError, match="valid integer"):
        Position.model_validate({"x": "1", "y": 0})

    with pytest.raises(ValidationError, match="valid boolean"):
        TileDefinition.model_validate(
            {
                "id": "floor",
                "walkable": "true",
                "appearance": "tile.floor",
            }
        )
