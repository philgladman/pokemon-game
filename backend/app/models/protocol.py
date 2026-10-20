from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from .common import Direction, Position, StrictModel
from .pokemon import PartyMember
from .story import ChoiceState, ControlMode, MapState, MovementCue, TransitionState


class MoveIntent(StrictModel):
    type: Literal["move"]
    request_id: str = Field(min_length=1, max_length=100)
    direction: Direction = Field(strict=False)
    continued: bool


class InteractIntent(StrictModel):
    type: Literal["interact"]
    request_id: str = Field(min_length=1, max_length=100)


class ChoiceIntent(StrictModel):
    type: Literal["choice"]
    request_id: str = Field(min_length=1, max_length=100)
    choice_id: str = Field(min_length=1, max_length=100)
    intent: Literal["previous", "next", "confirm", "cancel"]


class AcknowledgeCueIntent(StrictModel):
    type: Literal["acknowledge_cue"]
    request_id: str = Field(min_length=1, max_length=100)
    cue_id: str = Field(min_length=1, max_length=100)


class AcknowledgeTransitionIntent(StrictModel):
    type: Literal["acknowledge_transition"]
    request_id: str = Field(min_length=1, max_length=100)
    transition_id: str = Field(min_length=1, max_length=100)


ClientMessage = Annotated[
    MoveIntent | InteractIntent | ChoiceIntent | AcknowledgeCueIntent | AcknowledgeTransitionIntent,
    Field(discriminator="type"),
]
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
    "unsupported_interaction",
    "choice_opened",
    "choice_updated",
    "choice_closed",
    "scripted_movement",
    "movement_completed",
    "transition_completed",
    "phase_boundary",
]


class PlayerState(StrictModel):
    position: Position
    facing: Direction = Field(strict=False)
    sprite: str


class DialogState(StrictModel):
    interaction_id: str
    pages: list[str]
    page_index: int = Field(ge=0)


class SessionSnapshot(StrictModel):
    map: MapState
    player: PlayerState
    dialog: DialogState | None
    choice: ChoiceState | None
    control_mode: ControlMode
    movement_cue: MovementCue | None
    transition: TransitionState | None
    flags: list[str]
    has_starter: bool
    player_starter: str | None
    rival_starter: str | None
    party: list[PartyMember]


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
