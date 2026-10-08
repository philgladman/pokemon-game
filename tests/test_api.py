from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.models.assets import GltfAsset, PrimitiveAsset
from backend.app.models.map import WorldDefinition


def test_health_and_version(world: WorldDefinition) -> None:
    with TestClient(create_app(world)) as client:
        assert client.get("/api/health").json() == {"status": "ok"}
        assert client.get("/api/version").json() == {"version": "0.1.0"}


def test_manifest_glb_url_is_served_from_canonical_asset_root(
    world: WorldDefinition,
    tmp_path: Path,
) -> None:
    asset = GltfAsset(
        url="/assets/models/replacement.glb",
        fallback=PrimitiveAsset(shape="tree", color="#006600"),
    )
    model_path = tmp_path / asset.url.removeprefix("/assets/")
    model_path.parent.mkdir(parents=True)
    model_path.write_bytes(b"glTF-test-fixture")

    with TestClient(create_app(world, asset_root=tmp_path)) as client:
        response = client.get(asset.url)

    assert response.status_code == 200
    assert response.content == b"glTF-test-fixture"


def test_websocket_protocol_correlates_requests(world: WorldDefinition) -> None:
    with TestClient(create_app(world)) as client, client.websocket_connect("/ws/game") as socket:
        connected = socket.receive_json()
        assert connected["type"] == "state"
        assert connected["action"] == "connected"
        assert connected["state_version"] == 0

        socket.send_json({"type": "move", "request_id": "move-1", "direction": "south"})
        moved = socket.receive_json()
        assert moved["request_id"] == "move-1"
        assert moved["action"] == "moved"
        assert moved["state"]["player"]["position"] == {"x": 5, "y": 8}


def test_websocket_rejects_invalid_message_without_ending_session(world: WorldDefinition) -> None:
    with TestClient(create_app(world)) as client, client.websocket_connect("/ws/game") as socket:
        socket.receive_json()
        socket.send_json({"type": "move", "request_id": "bad-1", "direction": "upwards"})
        error = socket.receive_json()
        assert error == {
            "type": "error",
            "request_id": "bad-1",
            "code": "invalid_message",
            "message": "Message does not match the game protocol.",
        }

        socket.send_json({"type": "interact", "request_id": "still-open"})
        response = socket.receive_json()
        assert response["request_id"] == "still-open"
        assert response["action"] == "nothing_to_interact"


def test_websocket_recovers_from_malformed_json(world: WorldDefinition) -> None:
    with TestClient(create_app(world)) as client, client.websocket_connect("/ws/game") as socket:
        socket.receive_json()
        socket.send_text("{")

        error = socket.receive_json()
        assert error == {
            "type": "error",
            "request_id": None,
            "code": "invalid_message",
            "message": "Message does not match the game protocol.",
        }

        socket.send_json({"type": "move", "request_id": "after-error", "direction": "south"})
        response = socket.receive_json()
        assert response["request_id"] == "after-error"
        assert response["action"] == "moved"


def test_websocket_rejects_binary_frame_without_ending_session(world: WorldDefinition) -> None:
    with TestClient(create_app(world)) as client, client.websocket_connect("/ws/game") as socket:
        socket.receive_json()
        socket.send_bytes(b"{}")

        error = socket.receive_json()
        assert error == {
            "type": "error",
            "request_id": None,
            "code": "invalid_message",
            "message": "Message does not match the game protocol.",
        }

        socket.send_json({"type": "move", "request_id": "after-binary", "direction": "south"})
        response = socket.receive_json()
        assert response["request_id"] == "after-binary"
        assert response["action"] == "moved"


def test_each_websocket_has_an_isolated_session(world: WorldDefinition) -> None:
    with TestClient(create_app(world)) as client:
        with client.websocket_connect("/ws/game") as first:
            first.receive_json()
            first.send_json({"type": "move", "request_id": "one", "direction": "south"})
            assert first.receive_json()["state_version"] == 1
        with client.websocket_connect("/ws/game") as second:
            connected = second.receive_json()
            assert connected["state_version"] == 0
            assert connected["state"]["player"]["position"] == {"x": 5, "y": 7}
