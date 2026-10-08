from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import TypeAdapter, ValidationError
from starlette.staticfiles import StaticFiles

from backend.app.engine.game import ActionResult, GameSession
from backend.app.engine.repository import load_world
from backend.app.models.map import WorldDefinition
from backend.app.models.protocol import ClientMessage, ErrorMessage, InteractIntent, MoveIntent
from backend.app.version import __version__

logger = logging.getLogger("pokemon_game")
client_message_adapter: TypeAdapter[ClientMessage] = TypeAdapter(ClientMessage)
DEFAULT_ASSET_ROOT = Path(__file__).resolve().parents[2] / "assets"


def log_event(event: str, **fields: object) -> None:
    record = {"event": event, **fields}
    logger.info(json.dumps(record, sort_keys=True))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.world = load_world()
    log_event("game_data_loaded", outcome="success", maps=len(app.state.world.maps))
    yield


def create_app(
    world: WorldDefinition | None = None,
    asset_root: Path | None = None,
) -> FastAPI:
    app = FastAPI(title="Pallet Town 3D", version=__version__, lifespan=None if world else lifespan)
    if world is not None:
        app.state.world = world
    configured_asset_root = Path(os.environ.get("POKEMON_ASSETS_PATH", DEFAULT_ASSET_ROOT))
    app.mount(
        "/assets",
        StaticFiles(directory=asset_root or configured_asset_root, check_dir=True),
        name="assets",
    )

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/version")
    async def version() -> dict[str, str]:
        return {"version": __version__}

    @app.websocket("/ws/game")
    async def game_socket(websocket: WebSocket) -> None:
        await websocket.accept()
        session = GameSession(app.state.world)
        connected = session.response(None, ActionResult("connected"))
        await websocket.send_json(connected.model_dump(mode="json"))
        log_event("session_connected", outcome="success", map_id=session.map_id)

        try:
            while True:
                event = await websocket.receive()
                if event["type"] == "websocket.disconnect":
                    raise WebSocketDisconnect(event["code"], event.get("reason"))

                raw_text = event.get("text")
                if not isinstance(raw_text, str):
                    await _send_invalid_message(websocket)
                    continue

                raw_message: Any = None
                try:
                    raw_message = json.loads(raw_text)
                    message = client_message_adapter.validate_python(raw_message)
                except (json.JSONDecodeError, ValidationError):
                    await _send_invalid_message(websocket, _safe_request_id(raw_message))
                    continue

                if isinstance(message, MoveIntent):
                    result = session.move(message.direction)
                elif isinstance(message, InteractIntent):
                    result = session.interact()
                else:  # pragma: no cover - the discriminated union is exhaustive.
                    raise AssertionError("unhandled client message")
                response = session.response(message.request_id, result)
                await websocket.send_json(response.model_dump(mode="json"))
        except WebSocketDisconnect:
            log_event("session_disconnected", outcome="success", map_id=session.map_id)

    return app


async def _send_invalid_message(websocket: WebSocket, request_id: str | None = None) -> None:
    error = ErrorMessage(
        request_id=request_id,
        code="invalid_message",
        message="Message does not match the game protocol.",
    )
    await websocket.send_json(error.model_dump(mode="json"))


def _safe_request_id(message: Any) -> str | None:
    if not isinstance(message, Mapping):
        return None
    request_id = message.get("request_id")
    return request_id if isinstance(request_id, str) and len(request_id) <= 100 else None


app = create_app()
