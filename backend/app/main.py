from __future__ import annotations

import json
import logging
import os
from collections import OrderedDict
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import TypeAdapter, ValidationError
from starlette.staticfiles import StaticFiles

from backend.app.engine.game import ActionResult, GameSession
from backend.app.engine.repository import default_source, load_world
from backend.app.models.battle import BattleDefinition
from backend.app.models.map import WorldDefinition
from backend.app.models.protocol import (
    AcknowledgeBattleIntent,
    AcknowledgeCueIntent,
    AcknowledgeTransitionIntent,
    BattleActionIntent,
    ChoiceIntent,
    ClientMessage,
    ErrorMessage,
    InteractIntent,
    MoveIntent,
    StateMessage,
)
from backend.app.models.rendering import ThreeDManifest
from backend.app.models.story import StoryDefinition
from backend.app.presentation.three_d import load_three_d_manifest
from backend.app.source.provider import ApplicationSource, BattleSource
from backend.app.version import __version__

logger = logging.getLogger("pokemon_game")
client_message_adapter: TypeAdapter[ClientMessage] = TypeAdapter(ClientMessage)  # type: ignore[arg-type]
DEFAULT_ASSET_ROOT = Path(__file__).resolve().parents[2] / "assets"


def log_event(event: str, **fields: object) -> None:
    record = {"event": event, **fields}
    logger.info(json.dumps(record, sort_keys=True))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.world = load_world(app.state.source)
    app.state.story = app.state.source.build_story()
    battle_source: object = app.state.source
    if not isinstance(battle_source, BattleSource):
        raise RuntimeError("the application source must supply first-rival battle definitions")
    app.state.battle = battle_source.build_battle()
    _validate_three_d_resources(
        app.state.source,
        app.state.world,
        app.state.three_d_manifest,
    )
    log_event(
        "game_source_loaded",
        outcome="success",
        maps=len(app.state.world.maps),
        revision=app.state.world.source_revision,
    )
    yield


def _validate_three_d_resources(
    source: ApplicationSource,
    world: WorldDefinition,
    manifest: ThreeDManifest,
) -> None:
    appearances = set(manifest.as_registry())
    for map_id, map_definition in world.maps.items():
        resources = source.three_d_resources(map_id)
        expected_dimensions = (map_definition.height, map_definition.width)
        actual_dimensions = (
            len(resources.tile_appearances),
            {len(row) for row in resources.tile_appearances},
        )
        if actual_dimensions != (expected_dimensions[0], {expected_dimensions[1]}):
            raise RuntimeError(f"3D resources for {map_id} do not match logical map dimensions")
        referenced = {
            resources.player_appearance,
            *resources.npc_appearances.values(),
            *(appearance for row in resources.tile_appearances for appearance in row),
        }
        missing = referenced - appearances
        if missing:
            raise RuntimeError(
                f"3D resources for {map_id} reference missing appearances: {sorted(missing)}"
            )


def create_app(
    world: WorldDefinition | None = None,
    source: ApplicationSource | None = None,
    three_d_manifest: ThreeDManifest | None = None,
    asset_root: Path | None = None,
    story: StoryDefinition | None = None,
    battle: BattleDefinition | None = None,
) -> FastAPI:
    app = FastAPI(
        title="Pokémon Red compatibility runtime",
        version=__version__,
        lifespan=None if world else lifespan,
    )
    app.state.source = source or (None if world is not None else default_source())
    app.state.three_d_manifest = three_d_manifest or load_three_d_manifest()
    if world is not None:
        app.state.world = world
        app.state.story = story
        app.state.battle = battle
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

    @app.get("/source-assets/{category}/{name}.png", response_class=FileResponse)
    async def source_asset(category: str, name: str) -> FileResponse:
        configured_source: ApplicationSource | None = app.state.source
        if configured_source is None:
            raise HTTPException(status_code=404, detail="source assets unavailable")
        try:
            path = configured_source.resolve_asset(category, name)
        except RuntimeError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return FileResponse(path)

    @app.get("/api/renderers/retro/maps/{map_id}")
    async def retro_map_resources(map_id: str) -> object:
        configured_source: ApplicationSource | None = app.state.source
        if configured_source is None:
            raise HTTPException(status_code=404, detail="retro resources unavailable")
        try:
            return configured_source.retro_resources(map_id)
        except RuntimeError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get("/api/renderers/three-d/manifest")
    async def three_d_manifest_registry() -> object:
        configured_manifest: ThreeDManifest = app.state.three_d_manifest
        return configured_manifest.as_registry()

    @app.get("/api/renderers/three-d/maps/{map_id}")
    async def three_d_map_resources(map_id: str) -> object:
        configured_source: ApplicationSource | None = app.state.source
        if configured_source is None:
            raise HTTPException(status_code=404, detail="3D resources unavailable")
        try:
            return configured_source.three_d_resources(map_id)
        except RuntimeError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.websocket("/ws/game")
    async def game_socket(websocket: WebSocket) -> None:
        await websocket.accept()
        session = GameSession(app.state.world, app.state.story, app.state.battle)
        connected = session.response(None, ActionResult("connected"))
        await websocket.send_json(connected.model_dump(mode="json"))
        log_event("session_connected", outcome="success", map_id=session.map_id)
        replay_cache: OrderedDict[str, tuple[ClientMessage, StateMessage]] = OrderedDict()

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

                replay = replay_cache.get(message.request_id)
                if replay is not None:
                    previous_message, previous_response = replay
                    if previous_message != message:
                        await _send_invalid_message(websocket, message.request_id)
                    else:
                        await websocket.send_json(previous_response.model_dump(mode="json"))
                    continue

                if isinstance(message, MoveIntent):
                    result = session.move(message.direction, continued=message.continued)
                elif isinstance(message, InteractIntent):
                    result = session.interact()
                elif isinstance(message, ChoiceIntent):
                    result = session.choose(message.choice_id, message.intent)
                elif isinstance(message, AcknowledgeCueIntent):
                    result = session.acknowledge_cue(message.cue_id)
                elif isinstance(message, AcknowledgeTransitionIntent):
                    result = session.acknowledge_transition(message.transition_id)
                elif isinstance(message, BattleActionIntent):
                    result = session.battle_action(
                        message.battle_id, message.action_token, message.slot
                    )
                elif isinstance(message, AcknowledgeBattleIntent):
                    result = session.acknowledge_battle(message.battle_id, message.batch_id)
                else:  # pragma: no cover - the discriminated union is exhaustive.
                    raise AssertionError("unhandled client message")
                response = session.response(message.request_id, result)
                replay_cache[message.request_id] = (message, response)
                if len(replay_cache) > 256:
                    replay_cache.popitem(last=False)
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
