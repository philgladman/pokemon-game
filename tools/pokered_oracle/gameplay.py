from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from itertools import pairwise
from typing import Protocol

from backend.app.models.common import Direction, Position
from backend.app.models.map import WorldDefinition

from .emulator import OracleEmulator
from .errors import OracleError
from .runtime import RuntimeAdapter
from .trace import MotionPoint, MotionTrack, SemanticState


@dataclass(frozen=True)
class InteractionContract:
    id: str
    source_constant: str


@dataclass(frozen=True)
class MovementTiming:
    elapsed_frames: int
    turn_to_walk_frames: int | None
    tile_frames: tuple[int, ...]


class MovementBlocked(OracleError):
    """A transient live-world obstruction prevented a requested step."""


class GameplayDriver(Protocol):
    def capture(self, hook: str) -> SemanticState: ...

    def save_checkpoint(self, name: str) -> None: ...

    def load_checkpoint(self, name: str) -> None: ...

    def turn(self, direction: Direction) -> int: ...

    def walk_tiles(self, direction: Direction, count: int = 1) -> MovementTiming: ...

    def walk_to(self, target: Position) -> None: ...

    def exit_reds_house(self, column: int = 2) -> None: ...

    def begin_motion(self, actor_ids: tuple[str, ...]) -> None: ...

    def finish_motion(self) -> tuple[MotionTrack, ...]: ...

    def approach(self, target: Position) -> None: ...

    def approach_actor(self, actor_id: str) -> None: ...

    def interact(self, contract: InteractionContract) -> None: ...

    def interact_actor(self, actor_id: str, contract: InteractionContract) -> None: ...

    def dismiss_dialog(self) -> None: ...

    def expect_dialog(self, contract: InteractionContract) -> None: ...

    def advance_until(
        self,
        label: str,
        predicate: Callable[[SemanticState], bool],
        *,
        limit: int = 18_000,
    ) -> None: ...

    def prepare_choice(self) -> None: ...

    def choose(self, yes: bool) -> None: ...

    def capture_choice(self, hook: str) -> SemanticState: ...


class _Navigation:
    world: WorldDefinition
    _motion: dict[str, list[MotionPoint]] | None = None

    def begin_motion(self, actor_ids: tuple[str, ...]) -> None:
        self._motion = {actor_id: [] for actor_id in actor_ids}
        self._observe(self.capture("motion-start"))

    def finish_motion(self) -> tuple[MotionTrack, ...]:
        self._observe(self.capture("motion-end"))
        assert self._motion is not None
        tracks = tuple(
            MotionTrack(actor_id, tuple(points)) for actor_id, points in self._motion.items()
        )
        self._motion = None
        return tracks

    def _observe(self, state: SemanticState) -> None:
        if self._motion is None or state.map_id is None:
            return
        for actor_id in self._motion:
            if actor_id == "player":
                self._point(actor_id, MotionPoint(state.map_id, state.player_x, state.player_y))
                continue
            actor = next((actor for actor in state.actors or () if actor.id == actor_id), None)
            if actor is not None:
                self._point(
                    actor_id,
                    MotionPoint(
                        state.map_id,
                        actor.x if actor.visible else None,
                        actor.y if actor.visible else None,
                        actor.visible,
                    ),
                )

    def _point(self, actor_id: str, point: MotionPoint) -> None:
        if self._motion is None or actor_id not in self._motion:
            return
        points = self._motion[actor_id]
        if not points or points[-1] != point:
            points.append(point)

    def capture(self, hook: str) -> SemanticState:
        raise NotImplementedError

    def walk_tiles(self, direction: Direction, count: int = 1) -> MovementTiming:
        raise NotImplementedError

    def turn(self, direction: Direction) -> int:
        raise NotImplementedError

    def interact(self, contract: InteractionContract) -> None:
        raise NotImplementedError

    def walk_to(self, target: Position) -> None:
        initial_map = self.capture("navigate-start").map_id
        target_is_warp = bool(
            initial_map is not None
            and self.world.maps[initial_map].warp_at(target, "on_step") is not None
        )
        for _ in range(128):
            state = self.capture("navigate")
            if state.map_id != initial_map:
                if target_is_warp:
                    return
                raise OracleError(
                    f"navigation left {initial_map} before reaching ({target.x},{target.y})"
                )
            if (state.player_x, state.player_y) == (target.x, target.y):
                return
            path = self._path(Position(x=state.player_x or 0, y=state.player_y or 0), target)
            if not path:
                raise OracleError(
                    f"no live path in {state.map_id} from "
                    f"({state.player_x},{state.player_y}) to ({target.x},{target.y})"
                )
            before = (state.player_x, state.player_y)
            try:
                self.walk_tiles(path[0])
            except MovementBlocked:
                continue
            after = self.capture("navigate")
            if before == (after.player_x, after.player_y):
                continue
        raise OracleError(f"navigation did not converge on ({target.x},{target.y})")

    def approach(self, target: Position) -> None:
        state = self.capture("approach")
        start = Position(x=state.player_x or 0, y=state.player_y or 0)
        candidates: list[tuple[int, Position, Direction]] = []
        for direction in Direction:
            position = target.moved(_opposite(direction))
            path = self._path(start, position)
            if position == start or path:
                candidates.append((len(path), position, direction))
        if not candidates:
            raise OracleError(f"no interaction approach to ({target.x},{target.y})")
        _, position, direction = min(candidates, key=lambda item: item[0])
        self.walk_to(position)
        current = self.capture("approach-facing")
        if current.facing != direction.value:
            self.turn(direction)

    def approach_actor(self, actor_id: str) -> None:
        """Approach a live actor, recalculating if a walking NPC moved meanwhile."""

        for _ in range(16):
            state = self.capture(f"approach-{actor_id}")
            actor = visible_actor(state, actor_id)
            if actor is None:
                raise OracleError(f"actor {actor_id} is not visible in {state.map_id}")
            self.approach(Position(x=actor[0], y=actor[1]))
            current = self.capture(f"approach-{actor_id}-ready")
            live_actor = visible_actor(current, actor_id)
            if live_actor is None:
                raise OracleError(f"actor {actor_id} disappeared while approaching")
            player = Position(x=current.player_x or 0, y=current.player_y or 0)
            facing = Direction(current.facing or Direction.SOUTH.value)
            if player.moved(facing) == Position(x=live_actor[0], y=live_actor[1]):
                return
        raise OracleError(f"could not approach moving actor {actor_id}")

    def interact_actor(self, actor_id: str, contract: InteractionContract) -> None:
        self.approach_actor(actor_id)
        self.interact(contract)

    def _path(self, start: Position, target: Position) -> tuple[Direction, ...]:
        state = self.capture("path")
        if state.map_id is None:
            raise OracleError("cannot navigate without a current map")
        map_definition = self.world.maps[state.map_id]
        occupied = {
            (actor.x, actor.y)
            for actor in state.actors or ()
            if actor.visible and (actor.x, actor.y) != (target.x, target.y)
        }
        queue: deque[tuple[Position, tuple[Direction, ...]]] = deque([(start, ())])
        seen = {(start.x, start.y)}
        while queue:
            position, path = queue.popleft()
            if position == target:
                return path
            for direction in Direction:
                candidate = position.moved(direction)
                key = (candidate.x, candidate.y)
                if (
                    key in seen
                    or key in occupied
                    or not map_definition.contains(candidate)
                    or not map_definition.is_walkable(candidate)
                ):
                    continue
                seen.add(key)
                queue.append((candidate, (*path, direction)))
        return ()


class SourceGameplayDriver(_Navigation):
    def __init__(self, emulator: OracleEmulator, world: WorldDefinition) -> None:
        self.emulator = emulator
        self.world = world
        self._dialog_id: str | None = None
        self._display_hits = emulator.symbol_hits("DisplayTextID")

    def begin_motion(self, actor_ids: tuple[str, ...]) -> None:
        self._scripted_index: int | None = None
        self._warp_hits_start = self.emulator.symbol_hits("WarpFound2")
        super().begin_motion(actor_ids)
        self.emulator.observer = self._observe_source

    def _observe_source(self, state: SemanticState) -> None:
        # wCurMap changes before the new coordinates are installed. That first
        # frame still describes the source door tile, not a destination tile.
        if self._motion and (points := self._motion.get("player")):
            previous = points[-1]
            if (
                previous.map_id != state.map_id
                and state.player_x is not None
                and state.player_y is not None
            ):
                old_map = self.world.maps[previous.map_id]
                position = Position(x=state.player_x, y=state.player_y)
                if self.emulator.symbol_hits("WarpFound2") > self._warp_hits_start and any(
                    warp.position == position
                    and (old_map.last_map_target if warp.uses_last_map else warp.target_map)
                    == state.map_id
                    for warp in old_map.warps
                ):
                    self._point("player", MotionPoint(previous.map_id, position.x, position.y))
                    return
        scripted = bool(
            self.emulator.port.read(self.emulator.symbols["wStatusFlags5"].address) & 0x80
        )
        if (
            scripted
            and state.map_id == "PALLET_TOWN"
            and self._motion
            and "PALLETTOWN_OAK" in self._motion
        ):
            index = state.npc_movement_index or 0
            if self._scripted_index is not None and index > self._scripted_index:
                # This movement engine updates sprite pixels, leaving map tile
                # coordinates unchanged. Observe completed live buffer entries.
                points = self._motion["PALLETTOWN_OAK"]
                if points:
                    point = points[-1]
                    for offset in range(self._scripted_index, index):
                        value = self.emulator.port.read(
                            self.emulator.symbols["wNPCMovementDirections2"].address + offset
                        )
                        direction = {
                            0: Direction.SOUTH,
                            0x40: Direction.NORTH,
                            0x80: Direction.WEST,
                            0xC0: Direction.EAST,
                        }.get(value)
                        if direction is not None and point.x is not None and point.y is not None:
                            position = Position(x=point.x, y=point.y).moved(direction)
                            point = MotionPoint("PALLET_TOWN", position.x, position.y)
                            self._point("PALLETTOWN_OAK", point)
            self._scripted_index = index
            state = replace(
                state,
                actors=tuple(actor for actor in state.actors or () if actor.id != "PALLETTOWN_OAK"),
            )
        else:
            self._scripted_index = None
        self._observe(state)

    def finish_motion(self) -> tuple[MotionTrack, ...]:
        self.emulator.observer = None
        assert self._motion is not None
        tracks = tuple(
            MotionTrack(actor_id, tuple(points)) for actor_id, points in self._motion.items()
        )
        self._motion = None
        return tracks

    def capture(self, hook: str) -> SemanticState:
        state = self.emulator.capture(hook)
        return replace(
            state,
            dialog_id=self._dialog_id,
            control_mode="dialog" if self._dialog_id is not None else "free",
        )

    def save_checkpoint(self, name: str) -> None:
        self.emulator.save_checkpoint(name)

    def load_checkpoint(self, name: str) -> None:
        self.emulator.load_checkpoint(name)
        self._dialog_id = None
        self.emulator.tick()

    def turn(self, direction: Direction) -> int:
        start = self.capture("turn-start")
        if start.facing == direction.value:
            return 0
        start_frame = self.emulator.port.frame
        button = _button(direction)
        self.emulator.button_down(button)
        try:
            self.emulator.wait_for_symbol("JoypadOverworld", max_frames=4)
        finally:
            self.emulator.button_up(button)
        elapsed = self.emulator.port.frame - start_frame
        self.emulator.tick(2)
        end = self.capture("turn-end")
        if end.facing != direction.value:
            raise OracleError(f"one-poll tap did not turn {direction.value}")
        if (end.player_x, end.player_y) != (start.player_x, start.player_y):
            raise OracleError(f"turn-only input unexpectedly walked {direction.value}")
        return elapsed

    def exit_reds_house(self, column: int = 2) -> None:
        state = self.capture("house-exit-start")
        if state.map_id != "REDS_HOUSE_1F":
            raise OracleError(f"cannot exit Red's house from {state.map_id}")
        self.walk_to(Position(x=column, y=6))
        self.walk_tiles(Direction.SOUTH)

    def walk_tiles(self, direction: Direction, count: int = 1) -> MovementTiming:
        if count < 1:
            raise OracleError("walk tile count must be positive")
        start = self.capture("walk-start")
        start_frame = self.emulator.port.frame
        changed_direction = start.facing != direction.value
        transition_target = self._transition_target(start, direction) if count == 1 else None
        walking_frame: int | None = None
        changes: list[int] = []
        previous = (start.map_id, start.player_x, start.player_y)
        button = _button(direction)
        self.emulator.button_down(button)
        try:
            deadline = start_frame + count * 40 + 12
            while len(changes) < count and self.emulator.port.frame < deadline:
                self.emulator.tick()
                current = self.capture("walk")
                if walking_frame is None and current.walk_counter not in (None, 0):
                    walking_frame = self.emulator.port.frame
                location = (current.map_id, current.player_x, current.player_y)
                if location != previous:
                    changes.append(self.emulator.port.frame)
                    previous = location
            if len(changes) != count:
                raise MovementBlocked(
                    f"held {direction.value} moved {len(changes)} of {count} requested tiles"
                )
        finally:
            self.emulator.button_up(button)
        self.emulator.wait_until(
            f"finish {direction.value} tile",
            lambda emulator: emulator.capture("walk-finish").walk_counter == 0,
            max_frames=24,
        )
        self.emulator.tick()
        end_frame = self.emulator.port.frame
        if transition_target is not None:
            # Map object state is populated after the coordinate warp itself.
            self.emulator.tick(60)
            self.emulator.wait_until(
                "map transition controls",
                lambda emulator: self._at_transition_target(emulator, transition_target),
                max_frames=180,
            )
            end_frame = self.emulator.port.frame
        turn_to_walk = (
            walking_frame - start_frame if changed_direction and walking_frame is not None else None
        )
        # PyBoy returns after the frame that changed wWalkCounter. Include that
        # source advance's two frame boundaries when timing a turned first tile.
        first_interval = (
            changes[0] - walking_frame + 2
            if changed_direction and walking_frame is not None
            else changes[0] - start_frame
        )
        intervals = (
            first_interval,
            *(right - left for left, right in pairwise(changes)),
        )
        return MovementTiming(end_frame - start_frame, turn_to_walk, intervals)

    @staticmethod
    def _at_transition_target(emulator: OracleEmulator, target: tuple[str, int, int]) -> bool:
        state = emulator.capture("map-ready")
        return (state.map_id, state.player_x, state.player_y) == target and state.walk_counter == 0

    def _transition_target(
        self, state: SemanticState, direction: Direction
    ) -> tuple[str, int, int] | None:
        if state.map_id is None or state.player_x is None or state.player_y is None:
            return None
        source_map = self.world.maps[state.map_id]
        position = Position(x=state.player_x, y=state.player_y)
        warp = source_map.edge_exit_at(position, direction)
        if warp is None:
            destination = position.moved(direction)
            edge_warp = source_map.warp_at(destination, "edge_exit")
            if edge_warp is not None and edge_warp.outward == direction:
                warp = edge_warp
            else:
                warp = source_map.warp_at(destination, "on_step")
        if warp is None:
            return None
        target_map_id = source_map.last_map_target if warp.uses_last_map else warp.target_map
        if target_map_id is None:
            raise OracleError(f"warp {source_map.id}:{warp.index} has no target map")
        target_map = self.world.maps[target_map_id]
        target_warp = next(
            (candidate for candidate in target_map.warps if candidate.index == warp.target_warp),
            None,
        )
        if target_warp is None:
            raise OracleError(
                f"warp {source_map.id}:{warp.index} targets missing "
                f"{target_map_id}:{warp.target_warp}"
            )
        arrival = (
            target_warp.position.moved(direction)
            if warp.trigger == "edge_exit"
            else target_warp.position
        )
        return target_map_id, arrival.x, arrival.y

    def interact(self, contract: InteractionContract) -> None:
        if not self._try_interact(contract, max_frames=120):
            state = self.capture("interaction-timeout")
            raise OracleError(
                f"timed out after 120 frames waiting for interaction {contract.id}; "
                f"map={state.map_id} player=({state.player_x},{state.player_y}) "
                f"facing={state.facing}"
            )

    def interact_actor(self, actor_id: str, contract: InteractionContract) -> None:
        for _ in range(16):
            self.approach_actor(actor_id)
            if self._try_interact(contract, max_frames=12):
                return
        raise OracleError(f"could not interact with moving actor {actor_id}")

    def _try_interact(self, contract: InteractionContract, *, max_frames: int) -> bool:
        expected = self.emulator.metadata.text_id(contract.source_constant)
        initial_hits = self.emulator.symbol_hits("DisplayTextID")
        text_address = self.emulator.symbols["hTextID"].address
        initial_text = self.emulator.port.read(text_address)
        self.emulator.button_down("a")
        try:
            for _ in range(max_frames):
                actual = self.emulator.port.read(text_address)
                hits = self.emulator.symbol_hits("DisplayTextID")
                if actual == expected and (initial_text != expected or hits > initial_hits):
                    break
                if hits > initial_hits and self.emulator.last_display_text_id != expected:
                    raise OracleError(
                        f"source interaction {contract.id} opened text "
                        f"{self.emulator.last_display_text_id}, expected {expected}"
                    )
                self.emulator.tick()
            else:
                return False
        finally:
            self.emulator.button_up("a")
            self.emulator.tick()
        self._display_hits = self.emulator.symbol_hits("DisplayTextID")
        actual = self.emulator.port.read(text_address)
        if actual != expected:
            raise OracleError(
                f"source interaction {contract.id} opened text {actual}, expected {expected}"
            )
        self._dialog_id = contract.id
        return True

    def dismiss_dialog(self) -> None:
        if self._dialog_id is None:
            raise OracleError("no source dialog is open")
        self.emulator.press_until_symbol("a", "OverworldLoop", max_frames=3_600)
        self._dialog_id = None
        self.emulator.tick()

    def expect_dialog(self, contract: InteractionContract) -> None:
        expected = self.emulator.metadata.text_id(contract.source_constant)
        deadline = self.emulator.port.frame + 3_600
        neutral_deadline = min(deadline, self.emulator.port.frame + 60)
        while self.emulator.port.frame < deadline:
            hits = self.emulator.symbol_hits("DisplayTextID")
            if hits > self._display_hits:
                self._display_hits = hits
                actual = self.emulator.last_display_text_id
                if actual == expected:
                    self._dialog_id = contract.id
                    return
            if self.emulator.port.frame < neutral_deadline:
                self.emulator.tick()
            else:
                self.emulator.press("a", 2, 1)
        raise OracleError(f"source story did not open dialog {contract.id}")

    def advance_until(
        self,
        label: str,
        predicate: Callable[[SemanticState], bool],
        *,
        limit: int = 18_000,
    ) -> None:
        deadline = self.emulator.port.frame + limit
        while self.emulator.port.frame < deadline:
            state = self.capture(label)
            if predicate(state):
                return
            self.emulator.press("a", 1, 1)
        raise OracleError(f"source story did not reach {label} within {limit} frames")

    def prepare_choice(self) -> None:
        self.emulator.press_until_symbol(
            "a", "YesNoChoice", max_frames=3_600, hold_frames=2, settle_frames=1
        )
        self._dialog_id = None
        self.emulator.wait_for_symbol("HandleMenuInput_.loop2", max_frames=180)

    def capture_choice(self, hook: str) -> SemanticState:
        if self.emulator.port.read(self.emulator.symbols["wMaxMenuItem"].address) != 1:
            raise OracleError("source starter choice did not expose two menu options")
        if self.emulator.port.read(self.emulator.symbols["wTwoOptionMenuID"].address) != 0:
            raise OracleError("source starter choice did not open the Yes/No menu")
        return replace(
            self.capture(hook),
            control_mode="choice",
            choice_options=("YES", "NO"),
            choice_selected=self.emulator.port.read(
                self.emulator.symbols["wCurrentMenuItem"].address
            ),
        )

    def choose(self, yes: bool) -> None:
        if yes:
            self.emulator.press("a", 2, 2)
            self.emulator.tick()
            return
        self.emulator.press_until_symbol(
            "b", "OverworldLoop", max_frames=1_800, hold_frames=2, settle_frames=1
        )
        self.emulator.tick()


class RuntimeGameplayDriver(_Navigation):
    def __init__(self, runtime: RuntimeAdapter, world: WorldDefinition) -> None:
        self.runtime = runtime
        self.world = world

    def capture(self, hook: str) -> SemanticState:
        return self.runtime.capture(hook)

    def save_checkpoint(self, name: str) -> None:
        self.runtime.save_checkpoint(name)

    def load_checkpoint(self, name: str) -> None:
        self.runtime.load_checkpoint(name)

    def turn(self, direction: Direction) -> int:
        start = self.capture("turn-start")
        result = self.runtime.move(direction)
        if result.action != "turned":
            raise OracleError(f"runtime turn expected turned, got {result.action}")
        end = self.capture("turn-end")
        if (end.player_x, end.player_y) != (start.player_x, start.player_y):
            raise OracleError(f"runtime turn unexpectedly walked {direction.value}")
        return 2

    def exit_reds_house(self, column: int = 2) -> None:
        state = self.capture("house-exit-start")
        if state.map_id != "REDS_HOUSE_1F":
            raise OracleError(f"cannot exit Red's house from {state.map_id}")
        self.walk_to(Position(x=column, y=7))
        self.walk_tiles(Direction.SOUTH)

    def walk_tiles(self, direction: Direction, count: int = 1) -> MovementTiming:
        start = self.capture("walk-start")
        changed = start.facing != direction.value
        for index in range(count):
            before = self.capture("fresh-input")
            result = self.runtime.move(direction, continued=index > 0)
            if index == 0 and changed:
                after = self.capture("fresh-input-result")
                if result.action != "turned" or (after.player_x, after.player_y) != (
                    before.player_x,
                    before.player_y,
                ):
                    raise OracleError("changed fresh input must turn before held continuation")
            if result.action == "turned":
                result = self.runtime.move(direction, continued=True)
            if result.action not in {"moved", "transitioned", "dialog_opened"}:
                if result.action == "blocked":
                    raise MovementBlocked(f"runtime walk {direction.value} failed: {result}")
                raise OracleError(f"runtime walk {direction.value} failed: {result}")
            after = self.capture("walk-result")
            if before.map_id != after.map_id and before.map_id is not None:
                source_map = self.world.maps[before.map_id]
                position = Position(x=before.player_x or 0, y=before.player_y or 0)
                door = position.moved(direction)
                warp = source_map.edge_exit_at(position, direction)
                if warp is None:
                    warp = source_map.warp_at(door, "on_step")
                    self._point("player", MotionPoint(source_map.id, door.x, door.y))
                if warp is not None and warp.trigger == "edge_exit" and after.map_id is not None:
                    target = next(
                        item
                        for item in self.world.maps[after.map_id].warps
                        if item.index == warp.target_warp
                    )
                    self._point(
                        "player", MotionPoint(after.map_id, target.position.x, target.position.y)
                    )
            self._observe(self.capture("walk-result"))
            self._complete_transition()
            self._observe(self.capture("walk-complete"))
        return MovementTiming(
            count * 16 + (2 if changed else 0), 2 if changed else None, (16,) * count
        )

    def interact(self, contract: InteractionContract) -> None:
        result = self.runtime.interact()
        state = self.runtime.snapshot()
        if result.action != "dialog_opened" or state.dialog is None:
            raise OracleError(f"runtime interaction {contract.id} did not open dialog: {result}")
        if state.dialog.interaction_id != contract.id:
            raise OracleError(
                f"runtime interaction expected {contract.id}, got {state.dialog.interaction_id}"
            )

    def dismiss_dialog(self) -> None:
        if self.runtime.snapshot().dialog is None:
            raise OracleError("no runtime dialog is open")
        while self.runtime.snapshot().control_mode == "dialog":
            self.runtime.interact()

    def expect_dialog(self, contract: InteractionContract) -> None:
        self.advance_until(
            f"dialog {contract.id}",
            lambda state: state.control_mode == "dialog" and state.dialog_id == contract.id,
        )

    def advance_until(
        self,
        label: str,
        predicate: Callable[[SemanticState], bool],
        *,
        limit: int = 18_000,
    ) -> None:
        del limit
        for _ in range(256):
            state = self.capture(label)
            if predicate(state):
                return
            snapshot = self.runtime.snapshot()
            if snapshot.control_mode == "dialog":
                self.runtime.interact()
            elif snapshot.control_mode == "scripted_movement":
                self._observe(state)
                assert snapshot.movement_cue is not None
                for track in snapshot.movement_cue.tracks:
                    position = track.start
                    self._point(
                        track.actor_id, MotionPoint(snapshot.map.id, position.x, position.y)
                    )
                    for step in track.steps:
                        position = position.moved(step)
                        self._point(
                            track.actor_id, MotionPoint(snapshot.map.id, position.x, position.y)
                        )
                self.runtime.acknowledge_cue()
            elif snapshot.control_mode == "transition":
                self.runtime.acknowledge_transition()
            else:
                raise OracleError(
                    f"runtime story stalled in {snapshot.control_mode} before {label}"
                )
            self._observe(self.capture(label))
        raise OracleError(f"runtime story did not reach {label}")

    def prepare_choice(self) -> None:
        while self.runtime.snapshot().control_mode == "dialog":
            self.runtime.interact()
        if self.runtime.snapshot().control_mode != "choice":
            raise OracleError("runtime starter interaction did not open a choice")

    def choose(self, yes: bool) -> None:
        result = self.runtime.choose("confirm" if yes else "cancel")
        if result.action == "blocked":
            raise OracleError(f"runtime choice failed: {result.reason}")

    def capture_choice(self, hook: str) -> SemanticState:
        return self.capture(hook)

    def _complete_transition(self) -> None:
        if self.runtime.snapshot().control_mode == "transition":
            self.runtime.acknowledge_transition()


def visible_actor(state: SemanticState, actor_id: str) -> tuple[int, int, str] | None:
    actor = next((item for item in state.actors or () if item.id == actor_id), None)
    if actor is None or not actor.visible:
        return None
    return actor.x, actor.y, actor.facing


def project_state(
    state: SemanticState,
    hook: str,
    fields: Iterable[str],
    **overrides: object,
) -> SemanticState:
    fields = tuple(fields)
    values: dict[str, object] = {name: None for name in SemanticState.__dataclass_fields__}
    values["frame"] = state.frame
    values["hook"] = hook
    for name in fields:
        values[name] = getattr(state, name)
    values.update(overrides)
    values["compared_fields"] = tuple(dict.fromkeys((*fields, *overrides)))
    return SemanticState(**values)  # type: ignore[arg-type]


def _opposite(direction: Direction) -> Direction:
    return {
        Direction.NORTH: Direction.SOUTH,
        Direction.SOUTH: Direction.NORTH,
        Direction.EAST: Direction.WEST,
        Direction.WEST: Direction.EAST,
    }[direction]


def _button(direction: Direction) -> str:
    return {
        Direction.NORTH: "up",
        Direction.SOUTH: "down",
        Direction.EAST: "right",
        Direction.WEST: "left",
    }[direction]
