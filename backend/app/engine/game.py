from __future__ import annotations

from dataclasses import dataclass

from backend.app.models.common import Direction, Position
from backend.app.models.map import MapDefinition, NPCDefinition, WorldDefinition
from backend.app.models.protocol import (
    Action,
    DialogState,
    PlayerState,
    SessionSnapshot,
    StateMessage,
)


@dataclass(frozen=True)
class ActionResult:
    action: Action
    reason: str | None = None


class GameSession:
    """One isolated, server-authoritative game session."""

    def __init__(self, world: WorldDefinition) -> None:
        self._world = world
        self._map_id = world.start_map
        spawn = world.maps[self._map_id].player_spawn
        if spawn is None:  # Guarded by WorldDefinition; keeps the invariant local.
            raise ValueError("start map has no player spawn")
        self._player = PlayerState(
            position=spawn,
            facing=Direction.SOUTH,
            appearance=world.player_appearance,
        )
        self._dialog: DialogState | None = None
        self._version = 0

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
                asset_manifest=self._world.asset_manifest,
                player=self._player,
                dialog=self._dialog,
            ),
        )

    def move(self, direction: Direction) -> ActionResult:
        if self._dialog is not None:
            return ActionResult("blocked", "dialog_open")

        facing_changed = self._player.facing != direction
        if facing_changed:
            self._player = self._player.model_copy(update={"facing": direction})

        current_map = self._world.maps[self._map_id]
        destination = self._player.position.moved(direction)
        blocked_reason = self._blocked_reason(current_map, destination)
        if blocked_reason is not None:
            if facing_changed:
                self._version += 1
            return ActionResult("turned" if facing_changed else "blocked", blocked_reason)

        transition = current_map.transition_at(destination)
        if transition is not None:
            self._map_id = transition.target_map
            self._player = PlayerState(
                position=transition.target_position,
                facing=transition.target_facing,
                appearance=self._player.appearance,
            )
            self._version += 1
            return ActionResult("transitioned")

        self._player = PlayerState(
            position=destination,
            facing=direction,
            appearance=self._player.appearance,
        )
        self._version += 1
        return ActionResult("moved")

    def interact(self) -> ActionResult:
        if self._dialog is not None:
            next_index = self._dialog.line_index + 1
            if next_index < len(self._dialog.lines):
                self._dialog = self._dialog.model_copy(update={"line_index": next_index})
                self._version += 1
                return ActionResult("dialog_advanced")
            self._dialog = None
            self._version += 1
            return ActionResult("dialog_closed")

        target = self._player.position.moved(self._player.facing)
        npc = self._world.maps[self._map_id].npc_at(target)
        if npc is None:
            return ActionResult("nothing_to_interact")
        self._open_dialog(npc)
        return ActionResult("dialog_opened")

    def _open_dialog(self, npc: NPCDefinition) -> None:
        self._dialog = DialogState(
            npc_id=npc.id,
            speaker=npc.name,
            lines=npc.dialog,
            line_index=0,
        )
        self._version += 1

    @staticmethod
    def _blocked_reason(map_definition: MapDefinition, destination: Position) -> str | None:
        if not map_definition.contains(destination):
            return "map_boundary"
        if not map_definition.tile_at(destination).walkable:
            return "terrain"
        if map_definition.npc_at(destination) is not None:
            return "npc"
        return None
