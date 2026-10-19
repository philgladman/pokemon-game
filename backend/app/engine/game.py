from __future__ import annotations

from dataclasses import dataclass

from backend.app.models.common import Direction, Position
from backend.app.models.map import MapDefinition, TextInteraction, WarpDefinition, WorldDefinition
from backend.app.models.protocol import (
    Action,
    DialogState,
    PlayerState,
    SessionSnapshot,
    StateMessage,
)

from .text import resolve_text_pages


@dataclass(frozen=True)
class ActionResult:
    action: Action
    reason: str | None = None


class GameSession:
    """One isolated, server-authoritative game session."""

    def __init__(self, world: WorldDefinition) -> None:
        self._world = world
        self._map_id = world.start_map
        spawn = world.player_spawn
        self._player = PlayerState(
            position=spawn,
            facing=Direction.SOUTH,
            sprite=world.player_sprite,
        )
        self._dialog: DialogState | None = None
        self._version = 0
        self._input_continuous = False
        self._turn_check_armed = False
        self._last_stop_direction = Direction.SOUTH

    @property
    def state_version(self) -> int:
        return self._version

    @property
    def map_id(self) -> str:
        return self._map_id

    @property
    def player(self) -> PlayerState:
        return self._player

    @property
    def dialog(self) -> DialogState | None:
        return self._dialog

    def response(self, request_id: str | None, result: ActionResult) -> StateMessage:
        return StateMessage(
            request_id=request_id,
            state_version=self._version,
            action=result.action,
            reason=result.reason,
            state=SessionSnapshot(
                map=self._world.maps[self._map_id],
                player=self._player,
                dialog=self._dialog,
            ),
        )

    def move(self, direction: Direction, *, continued: bool = False) -> ActionResult:
        if self._dialog is not None:
            return ActionResult("blocked", "dialog_open")

        if not continued or not self._input_continuous:
            self._input_continuous = True
            self._turn_check_armed = True
            self._last_stop_direction = self._player.facing

        facing_changed = self._player.facing != direction
        if self._turn_check_armed and direction != self._last_stop_direction:
            self._turn_check_armed = False
            if facing_changed:
                self._player = self._player.model_copy(update={"facing": direction})
                self._version += 1
            return ActionResult("turned", "direction_change")

        if facing_changed:
            self._player = self._player.model_copy(update={"facing": direction})

        current_map = self._world.maps[self._map_id]
        edge_exit = current_map.edge_exit_at(self._player.position, direction)
        if edge_exit is not None:
            return self._transition(current_map, edge_exit, direction)

        destination = self._player.position.moved(direction)
        blocked_reason = self._blocked_reason(current_map, destination)
        if blocked_reason is not None:
            if facing_changed:
                self._version += 1
            return ActionResult("blocked", blocked_reason)

        warp = current_map.warp_at(destination, "on_step")
        if warp is not None:
            return self._transition(current_map, warp, direction)

        self._player = PlayerState(
            position=destination,
            facing=direction,
            sprite=self._player.sprite,
        )
        self._version += 1
        return ActionResult("moved")

    def _transition(
        self,
        current_map: MapDefinition,
        warp: WarpDefinition,
        direction: Direction,
    ) -> ActionResult:
        target_map_id = current_map.last_map_target if warp.uses_last_map else warp.target_map
        if target_map_id is None:
            return ActionResult("blocked", "missing_last_map")
        target_map = self._world.maps[target_map_id]
        target_warp = next(
            (candidate for candidate in target_map.warps if candidate.index == warp.target_warp),
            None,
        )
        if target_warp is None:
            return ActionResult("blocked", "missing_target_warp")
        arrival_direction = warp.outward if warp.trigger == "edge_exit" else direction
        assert arrival_direction is not None
        arrival = (
            target_warp.position.moved(arrival_direction)
            if warp.trigger == "edge_exit"
            else target_warp.position
        )
        if self._blocked_reason(target_map, arrival) is not None:
            return ActionResult("blocked", "invalid_warp_landing")
        self._map_id = target_map_id
        self._player = PlayerState(
            position=arrival,
            facing=arrival_direction,
            sprite=self._player.sprite,
        )
        self._version += 1
        self._reset_input_continuity()
        return ActionResult("transitioned")

    def interact(self) -> ActionResult:
        if self._dialog is not None:
            next_index = self._dialog.page_index + 1
            if next_index < len(self._dialog.pages):
                self._dialog = self._dialog.model_copy(update={"page_index": next_index})
                self._version += 1
                return ActionResult("dialog_advanced")
            self._dialog = None
            self._version += 1
            self._reset_input_continuity()
            return ActionResult("dialog_closed")

        target = self._player.position.moved(self._player.facing)
        current_map = self._world.maps[self._map_id]
        npc = current_map.npc_at(target)
        if npc is not None:
            return self._open_dialog(npc.id, npc.interaction)
        background = current_map.background_event_at(target)
        if background is not None:
            return self._open_dialog(background.interaction.reference, background.interaction)
        return ActionResult("nothing_to_interact")

    def _open_dialog(self, interaction_id: str, interaction: TextInteraction) -> ActionResult:
        if interaction.status == "unsupported":
            return ActionResult("unsupported_interaction", interaction.reason)
        self._dialog = DialogState(
            interaction_id=interaction_id,
            pages=resolve_text_pages(
                interaction.template_pages,
                self._world.text_variables,
            ),
            page_index=0,
        )
        self._version += 1
        self._reset_input_continuity()
        return ActionResult("dialog_opened")

    def _reset_input_continuity(self) -> None:
        self._input_continuous = False
        self._turn_check_armed = False
        self._last_stop_direction = self._player.facing

    @staticmethod
    def _blocked_reason(map_definition: MapDefinition, destination: Position) -> str | None:
        if not map_definition.contains(destination):
            return "map_boundary"
        if not map_definition.is_walkable(destination):
            return "terrain"
        if map_definition.npc_at(destination) is not None:
            return "npc"
        return None
