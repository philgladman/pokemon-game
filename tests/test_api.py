from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.main import _validate_three_d_resources, create_app
from backend.app.models.common import Direction
from backend.app.models.map import WorldDefinition
from backend.app.models.rendering import (
    RetroMapResources,
    SourceAsset,
    ThreeDManifest,
    ThreeDMapResources,
)
from backend.app.models.story import (
    ActorState,
    ChoiceCommand,
    ChoiceOption,
    InteractionTrigger,
    StoryDefinition,
    StoryNode,
)
from backend.app.presentation.three_d import load_three_d_manifest


class FixtureSource:
    def __init__(self, world: WorldDefinition, asset: Path) -> None:
        self.root = asset.parent
        self.revision = world.source_revision
        self._world = world
        self._asset = asset

    def build_world(self) -> WorldDefinition:
        return self._world

    def resolve_asset(self, category: str, name: str) -> Path:
        if (category, name) != ("sprites", "fixture"):
            raise RuntimeError("not allowlisted")
        return self._asset

    def retro_resources(self, map_id: str) -> RetroMapResources:
        if map_id != "OUTDOOR":
            raise RuntimeError("not allowlisted")
        return RetroMapResources(
            map_id=map_id,
            tileset="FIXTURE",
            tileset_asset=SourceAsset(
                kind="tileset",
                name="fixture",
                url="/source-assets/tilesets/fixture.png",
            ),
            tile_ids=[[0] * 8 for _ in range(8)],
            block_ids=[[0] * 2 for _ in range(2)],
            player_asset=SourceAsset(
                kind="sprite",
                name="fixture",
                url="/source-assets/sprites/fixture.png",
            ),
            sprite_assets={},
        )

    def three_d_resources(self, map_id: str) -> ThreeDMapResources:
        map_definition = self._world.maps.get(map_id)
        if map_definition is None:
            raise RuntimeError("not allowlisted")
        return ThreeDMapResources(
            map_id=map_id,
            tile_appearances=[
                ["tile.path"] * map_definition.width for _ in range(map_definition.height)
            ],
            player_appearance="character.player",
            npc_appearances={npc.id: "character.npc" for npc in map_definition.npcs},
        )


def test_health_and_version(world: WorldDefinition) -> None:
    with TestClient(create_app(world)) as client:
        assert client.get("/api/health").json() == {"status": "ok"}
        assert client.get("/api/version").json() == {"version": "0.3.0"}


def test_source_asset_endpoint_only_serves_provider_allowlist(
    world: WorldDefinition, tmp_path: Path
) -> None:
    asset = tmp_path / "fixture.png"
    asset.write_bytes(b"png-fixture")
    source = FixtureSource(world, asset)

    with TestClient(create_app(world, source)) as client:
        allowed = client.get("/source-assets/sprites/fixture.png")
        denied = client.get("/source-assets/sprites/secret.png")

    assert allowed.status_code == 200
    assert allowed.content == b"png-fixture"
    assert denied.status_code == 404


def test_retro_resources_are_separate_from_authoritative_snapshot(
    world: WorldDefinition, tmp_path: Path
) -> None:
    asset = tmp_path / "fixture.png"
    asset.write_bytes(b"png-fixture")
    source = FixtureSource(world, asset)

    with TestClient(create_app(world, source)) as client:
        resources = client.get("/api/renderers/retro/maps/OUTDOOR")
        missing = client.get("/api/renderers/retro/maps/UNKNOWN")
        with client.websocket_connect("/ws/game") as socket:
            snapshot = socket.receive_json()["state"]

    assert resources.status_code == 200
    assert resources.json()["tileset_asset"]["url"].startswith("/source-assets/")
    assert missing.status_code == 404
    assert "graphics" not in snapshot["map"]
    assert snapshot["player"]["sprite"] == "SPRITE_RED"


def test_three_d_resources_and_manifest_are_separate_from_snapshot(
    world: WorldDefinition, tmp_path: Path
) -> None:
    asset = tmp_path / "fixture.png"
    asset.write_bytes(b"png-fixture")
    source = FixtureSource(world, asset)

    with TestClient(create_app(world, source)) as client:
        manifest = client.get("/api/renderers/three-d/manifest")
        resources = client.get("/api/renderers/three-d/maps/OUTDOOR")
        missing = client.get("/api/renderers/three-d/maps/UNKNOWN")
        with client.websocket_connect("/ws/game") as socket:
            snapshot = socket.receive_json()["state"]

    assert manifest.status_code == 200
    assert manifest.json()["character.player"]["source"]["type"] == "primitive"
    assert resources.status_code == 200
    assert resources.json()["tile_appearances"][0][0] == "tile.path"
    assert missing.status_code == 404
    assert "asset_manifest" not in snapshot
    assert "tile_appearances" not in snapshot["map"]


def test_three_d_projection_is_validated_against_logical_maps_and_manifest(
    world: WorldDefinition, tmp_path: Path
) -> None:
    asset = tmp_path / "fixture.png"
    asset.write_bytes(b"png-fixture")
    source = FixtureSource(world, asset)

    _validate_three_d_resources(source, world, load_three_d_manifest())

    with pytest.raises(RuntimeError, match="missing appearances"):
        _validate_three_d_resources(source, world, ThreeDManifest(appearances=[]))


def test_websocket_protocol_correlates_requests(world: WorldDefinition) -> None:
    with TestClient(create_app(world)) as client, client.websocket_connect("/ws/game") as socket:
        assert socket.receive_json()["action"] == "connected"
        socket.send_json(
            {
                "type": "move",
                "request_id": "move-1",
                "direction": "north",
                "continued": False,
            }
        )
        turned = socket.receive_json()
        socket.send_json(
            {
                "type": "move",
                "request_id": "move-2",
                "direction": "north",
                "continued": True,
            }
        )
        blocked = socket.receive_json()

    assert turned["request_id"] == "move-1"
    assert turned["action"] == "turned"
    assert blocked["request_id"] == "move-2"
    assert blocked["action"] == "blocked"
    assert blocked["state"]["player"]["position"] == {"x": 1, "y": 1}


def test_websocket_rejects_invalid_message_without_ending_session(
    world: WorldDefinition,
) -> None:
    with TestClient(create_app(world)) as client, client.websocket_connect("/ws/game") as socket:
        socket.receive_json()
        socket.send_json(
            {
                "type": "move",
                "request_id": "bad-1",
                "direction": "upwards",
                "continued": False,
            }
        )
        error = socket.receive_json()
        socket.send_json({"type": "interact", "request_id": "still-open"})
        response = socket.receive_json()

    assert error["code"] == "invalid_message"
    assert response["request_id"] == "still-open"


def test_each_websocket_has_an_isolated_session(world: WorldDefinition) -> None:
    with TestClient(create_app(world)) as client:
        with client.websocket_connect("/ws/game") as first:
            first.receive_json()
            first.send_json(
                {
                    "type": "move",
                    "request_id": "one",
                    "direction": "north",
                    "continued": False,
                }
            )
            assert first.receive_json()["state_version"] == 1
        with client.websocket_connect("/ws/game") as second:
            assert second.receive_json()["state_version"] == 0


def test_story_choice_and_cue_messages_are_typed_and_correlated(
    pokered_world: WorldDefinition,
    pokered_story: StoryDefinition,
) -> None:
    with (
        TestClient(create_app(pokered_world, story=pokered_story)) as client,
        client.websocket_connect("/ws/game") as socket,
    ):
        connected = socket.receive_json()
        socket.send_json(
            {
                "type": "choice",
                "request_id": "choice-1",
                "choice_id": "unknown",
                "intent": "confirm",
            }
        )
        choice = socket.receive_json()
        socket.send_json(
            {
                "type": "acknowledge_cue",
                "request_id": "cue-1",
                "cue_id": "unknown",
            }
        )
        cue = socket.receive_json()

    assert connected["state"]["map"]["id"] == "REDS_HOUSE_2F"
    assert choice["request_id"] == "choice-1"
    assert (choice["action"], choice["reason"]) == ("blocked", "choice_not_open")
    assert cue["request_id"] == "cue-1"
    assert (cue["action"], cue["reason"]) == ("blocked", "stale_movement_cue")


def test_websocket_serializes_story_owned_source_fallback_dialog(
    world: WorldDefinition,
) -> None:
    story = StoryDefinition(
        start_map=world.start_map,
        start_position=world.player_spawn,
        start_facing=Direction.SOUTH,
        event_flags=frozenset(),
        initial_actors={
            map_id: tuple(
                ActorState(
                    id=npc.id,
                    position=npc.position,
                    facing=npc.facing,
                    visible=npc.visible,
                    sprite=npc.sprite,
                )
                for npc in map_definition.npcs
            )
            for map_id, map_definition in world.maps.items()
        },
        texts={},
        movements={},
        starters={},
        nodes=(),
        provenance=world.maps[world.start_map].provenance,
    )
    with (
        TestClient(create_app(world, story=story)) as client,
        client.websocket_connect("/ws/game") as socket,
    ):
        socket.receive_json()
        socket.send_json({"type": "interact", "request_id": "source-dialog"})
        opened = socket.receive_json()

    assert opened["request_id"] == "source-dialog"
    assert opened["action"] == "dialog_opened"
    assert opened["state"]["control_mode"] == "dialog"
    assert opened["state"]["dialog"] == {
        "interaction_id": "PERSON",
        "pages": ["Source page one", "Source page two"],
        "page_index": 0,
    }


def test_websocket_choice_instances_reject_stale_input_and_replay_duplicate_requests(
    world: WorldDefinition,
) -> None:
    provenance = world.maps["OUTDOOR"].provenance
    person = world.maps["OUTDOOR"].npcs[0]
    options = (ChoiceOption(id="yes", label="YES"), ChoiceOption(id="no", label="NO"))
    story = StoryDefinition(
        start_map="OUTDOOR",
        start_position=world.player_spawn,
        start_facing=Direction.SOUTH,
        event_flags=frozenset(),
        initial_actors={
            "OUTDOOR": (
                ActorState(
                    id=person.id,
                    position=person.position,
                    facing=person.facing,
                    visible=person.visible,
                    sprite=person.sprite,
                ),
            ),
            "INDOOR": (),
        },
        texts={},
        movements={},
        starters={},
        nodes=(
            StoryNode(
                id="choose",
                trigger=InteractionTrigger(map_id="OUTDOOR", actor_id="PERSON"),
                commands=(
                    ChoiceCommand(
                        id="fixture_choice",
                        prompt="Choose?",
                        options=options,
                        cancel_index=1,
                        branches={"yes": ("yes_end",), "no": ("no_end",)},
                    ),
                ),
                provenance=provenance,
            ),
            StoryNode(id="yes_end", provenance=provenance),
            StoryNode(id="no_end", provenance=provenance),
        ),
        provenance=provenance,
    )

    with (
        TestClient(create_app(world, story=story)) as client,
        client.websocket_connect("/ws/game") as socket,
    ):
        socket.receive_json()
        socket.send_json({"type": "interact", "request_id": "open-1"})
        opened = socket.receive_json()
        first_id = opened["state"]["choice"]["instance_id"]
        next_message = {
            "type": "choice",
            "request_id": "next-1",
            "choice_id": first_id,
            "intent": "next",
        }
        socket.send_json(next_message)
        advanced = socket.receive_json()
        socket.send_json(next_message)
        replayed = socket.receive_json()
        socket.send_json(
            {
                "type": "choice",
                "request_id": "confirm-1",
                "choice_id": first_id,
                "intent": "confirm",
            }
        )
        socket.receive_json()
        socket.send_json({"type": "interact", "request_id": "open-2"})
        reopened = socket.receive_json()
        second_id = reopened["state"]["choice"]["instance_id"]
        socket.send_json(
            {
                "type": "choice",
                "request_id": "stale-confirm",
                "choice_id": first_id,
                "intent": "confirm",
            }
        )
        stale = socket.receive_json()

    assert advanced == replayed
    assert advanced["state"]["choice"]["selected_index"] == 1
    assert second_id != first_id
    assert (stale["action"], stale["reason"]) == ("blocked", "stale_choice")
    assert stale["state"]["choice"]["instance_id"] == second_id
