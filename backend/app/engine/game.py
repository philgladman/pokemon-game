from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from backend.app.models.common import Direction, Position
from backend.app.models.map import MapDefinition, TextInteraction, WarpDefinition, WorldDefinition
from backend.app.models.protocol import (
    Action,
    DialogState,
    PlayerState,
    SessionSnapshot,
    StateMessage,
)
from backend.app.models.story import ActorState, MapState, StoryDefinition

from .story import StoryRunner
from .text import resolve_text_pages


@dataclass(frozen=True)
class ActionResult:
    action: Action
    reason: str | None = None


class GameSession:
    """One isolated, server-authoritative game session."""

    def __init__(self, world: WorldDefinition, story: StoryDefinition | None = None) -> None:
        self._world = world
        self._story = StoryRunner(world, story) if story is not None else None
        self._map_id = self._story.map_id if self._story is not None else world.start_map
        spawn = self._story.player.position if self._story is not None else world.player_spawn
        self._player = PlayerState(
            position=spawn,
            facing=self._story.player.facing if self._story is not None else Direction.SOUTH,
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
        return self._story.map_id if self._story is not None else self._map_id

    @property
    def player(self) -> PlayerState:
        return self._story.player if self._story is not None else self._player

    @property
    def dialog(self) -> DialogState | None:
        return self._story.dialog if self._story is not None else self._dialog

    def response(self, request_id: str | None, result: ActionResult) -> StateMessage:
        return StateMessage(
            request_id=request_id,
            state_version=self._version,
            action=result.action,
            reason=result.reason,
            state=SessionSnapshot(
                map=self._map_state(),
                player=self.player,
                dialog=self.dialog,
                choice=self._story.choice if self._story is not None else None,
                control_mode=self._story.control_mode
                if self._story is not None
                else ("dialog" if self._dialog is not None else "free"),
                movement_cue=self._story.movement_cue if self._story is not None else None,
                transition=self._story.transition if self._story is not None else None,
                flags=sorted(self._story.flags) if self._story is not None else [],
                has_starter=self._story.has_starter if self._story is not None else False,
                player_starter=self._story.player_starter if self._story is not None else None,
                rival_starter=self._story.rival_starter if self._story is not None else None,
                party=list(self._story.party) if self._story is not None else [],
            ),
        )

    def move(self, direction: Direction, *, continued: bool = False) -> ActionResult:
        if self.dialog is not None:
            return ActionResult("blocked", "dialog_open")
        if self._story is not None and self._story.control_mode != "free":
            return ActionResult("blocked", f"control_{self._story.control_mode}")

        if not continued or not self._input_continuous:
            self._input_continuous = True
            self._turn_check_armed = True
            self._last_stop_direction = self.player.facing

        facing_changed = self.player.facing != direction
        if self._turn_check_armed and direction != self._last_stop_direction:
            self._turn_check_armed = False
            if facing_changed:
                self._set_player(self.player.model_copy(update={"facing": direction}))
                self._version += 1
            return ActionResult("turned", "direction_change")

        if facing_changed:
            self._set_player(self.player.model_copy(update={"facing": direction}))

        current_map = self._world.maps[self.map_id]
        edge_exit = current_map.edge_exit_at(self.player.position, direction)
        if edge_exit is not None:
            return self._transition(current_map, edge_exit, direction)

        destination = self.player.position.moved(direction)
        if self._story is not None:
            story_result = self._story.before_move(destination)
            if story_result is not None:
                self._version += 1
                self._reset_input_continuity()
                return ActionResult(cast(Action, story_result.action), story_result.reason)
        blocked_reason = self._runtime_blocked_reason(current_map, destination)
        if blocked_reason is not None:
            if facing_changed:
                self._version += 1
            return ActionResult("blocked", blocked_reason)

        warp = current_map.warp_at(destination, "on_step")
        if warp is not None:
            return self._transition(current_map, warp, direction)

        self._set_player(
            PlayerState(
                position=destination,
                facing=direction,
                sprite=self.player.sprite,
            )
        )
        self._version += 1
        if self._story is not None:
            story_result = self._story.after_move()
            if story_result is not None:
                self._reset_input_continuity()
                return ActionResult(cast(Action, story_result.action), story_result.reason)
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
        if self._runtime_blocked_reason(target_map, arrival) is not None:
            return ActionResult("blocked", "invalid_warp_landing")
        self._map_id = target_map_id
        self._set_player(
            PlayerState(
                position=arrival,
                facing=arrival_direction,
                sprite=self.player.sprite,
            ),
            map_id=target_map_id,
        )
        self._version += 1
        self._reset_input_continuity()
        if self._story is not None:
            story_result = self._story.after_transition()
            if story_result is not None:
                return ActionResult(cast(Action, story_result.action), story_result.reason)
        return ActionResult("transitioned")

    def interact(self) -> ActionResult:
        if self._story is not None and self._story.control_mode == "dialog":
            story_result = self._story.advance_dialog()
            self._version += 1
            self._reset_input_continuity()
            return ActionResult(cast(Action, story_result.action), story_result.reason)
        if self._story is not None and self._story.control_mode != "free":
            return ActionResult("blocked", f"control_{self._story.control_mode}")
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

        target = self.player.position.moved(self.player.facing)
        current_map = self._world.maps[self.map_id]
        actor = self._story.actor_at(self.map_id, target) if self._story is not None else None
        npc = (
            next(
                (candidate for candidate in current_map.npcs if candidate.id == actor.id),
                None,
            )
            if actor is not None
            else None
        )
        if self._story is None:
            npc = current_map.npc_at(target)
        background = current_map.background_event_at(target)
        if self._story is not None:
            interaction_result = self._story.interact(actor, npc, background)
            if interaction_result is not None:
                self._version += 1
                self._reset_input_continuity()
                return ActionResult(
                    cast(Action, interaction_result.action), interaction_result.reason
                )
        if npc is not None:
            return self._open_dialog(npc.id, npc.interaction)
        if background is not None:
            return self._open_dialog(background.interaction.reference, background.interaction)
        return ActionResult("nothing_to_interact")

    def choose(self, choice_id: str, intent: str) -> ActionResult:
        if self._story is None:
            return ActionResult("blocked", "choice_not_open")
        result = self._story.choose(choice_id, intent)
        if result.action != "blocked":
            self._version += 1
        self._reset_input_continuity()
        return ActionResult(cast(Action, result.action), result.reason)

    def acknowledge_cue(self, cue_id: str) -> ActionResult:
        if self._story is None:
            return ActionResult("blocked", "stale_movement_cue")
        result = self._story.acknowledge_cue(cue_id)
        if result.action != "blocked":
            self._version += 1
        self._reset_input_continuity()
        return ActionResult(cast(Action, result.action), result.reason)

    def acknowledge_transition(self, transition_id: str) -> ActionResult:
        if self._story is None:
            return ActionResult("blocked", "stale_transition")
        result = self._story.acknowledge_transition(transition_id)
        if result.action != "blocked":
            self._version += 1
        self._reset_input_continuity()
        return ActionResult(cast(Action, result.action), result.reason)

    def _open_dialog(self, interaction_id: str, interaction: TextInteraction) -> ActionResult:
        if interaction.status == "unsupported":
            return ActionResult("unsupported_interaction", interaction.reason)
        if self._story is not None:
            self._story.open_source_dialog(interaction_id, interaction)
        else:
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
        self._last_stop_direction = self.player.facing

    def _map_state(self) -> MapState:
        if self._story is not None:
            return self._story.map_state()
        source = self._world.maps[self._map_id]
        return MapState(
            id=source.id,
            source_name=source.source_name,
            kind=source.kind,
            last_map_target=source.last_map_target,
            width=source.width,
            height=source.height,
            walkable=source.walkable,
            actors=[
                ActorState(
                    id=npc.id,
                    position=npc.position,
                    facing=npc.facing,
                    visible=npc.visible,
                    sprite=npc.sprite,
                )
                for npc in source.npcs
            ],
        )

    def _set_player(self, player: PlayerState, *, map_id: str | None = None) -> None:
        self._player = player
        if self._story is not None:
            self._story.set_player(map_id or self._story.map_id, player)

    def _runtime_blocked_reason(
        self, map_definition: MapDefinition, destination: Position
    ) -> str | None:
        reason = self._blocked_reason(map_definition, destination)
        if reason == "npc" and self._story is not None:
            return "npc" if self._story.actor_at(map_definition.id, destination) else None
        if reason is None and self._story is not None:
            return "npc" if self._story.actor_at(map_definition.id, destination) else None
        return reason

    @staticmethod
    def _blocked_reason(map_definition: MapDefinition, destination: Position) -> str | None:
        if not map_definition.contains(destination):
            return "map_boundary"
        if not map_definition.is_walkable(destination):
            return "terrain"
        if map_definition.npc_at(destination) is not None:
            return "npc"
        return None
