from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from .assets import AppearanceDefinition
from .common import Direction, Position, StrictModel
from .map import MapDefinition


class MoveIntent(StrictModel):
    type: Literal["move"]
    request_id: str = Field(min_length=1, max_length=100)
    direction: Direction = Field(strict=False)


class InteractIntent(StrictModel):
    type: Literal["interact"]
    request_id: str = Field(min_length=1, max_length=100)


ClientMessage = Annotated[MoveIntent | InteractIntent, Field(discriminator="type")]
Action = Literal[
    "connected",
    "moved",
    "blocked",
    "turned",
    "transitioned",
    "dialog_opened",
    "dialog_advanced",
    "dialog_closed",
    "nothing_to_interact",
]


class PlayerState(StrictModel):
    position: Position
    facing: Direction = Field(strict=False)
    appearance: str


class DialogState(StrictModel):
    npc_id: str
    speaker: str
    lines: list[str]
    line_index: int = Field(ge=0)


class SessionSnapshot(StrictModel):
    map: MapDefinition
    asset_manifest: dict[str, AppearanceDefinition]
    player: PlayerState
    dialog: DialogState | None


class StateMessage(StrictModel):
    type: Literal["state"] = "state"
    request_id: str | None
    state_version: int = Field(ge=0)
    action: Action
    reason: str | None = None
    state: SessionSnapshot


class ErrorMessage(StrictModel):
    type: Literal["error"] = "error"
    request_id: str | None
    code: Literal["invalid_message", "internal_error"]
    message: str
