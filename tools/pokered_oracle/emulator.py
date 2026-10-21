from __future__ import annotations

import importlib
from collections.abc import Callable
from io import BytesIO
from typing import Protocol, cast

from backend.app.models.map import WorldDefinition

from .artifacts import BuildArtifacts, require_pyboy
from .errors import OracleError, OraclePrerequisiteError
from .metadata import SourceMetadata, normalize_facing
from .symbols import SymbolTable
from .trace import ActorTrace, SemanticState


class EmulatorPort(Protocol):
    @property
    def frame(self) -> int: ...

    def tick(self, frames: int = 1) -> None: ...

    def press(self, button: str, hold_frames: int = 1, settle_frames: int = 1) -> None: ...

    def button_down(self, button: str) -> None: ...

    def button_up(self, button: str) -> None: ...

    def read(self, address: int) -> int: ...

    def register(self, name: str) -> int: ...

    def save_checkpoint(self, name: str) -> None: ...

    def load_checkpoint(self, name: str) -> None: ...

    def hook(self, bank: int, address: int, callback: Callable[[object], None]) -> None: ...

    def stop(self) -> None: ...


class PyBoyAdapter:
    """Small lazy adapter around the exact PyBoy API used by the oracle."""

    def __init__(self, artifacts: BuildArtifacts) -> None:
        require_pyboy()
        sidecars = tuple(
            path
            for suffix in (".ram", ".rtc")
            if (path := artifacts.rom.with_suffix(suffix)).exists()
        )
        if sidecars:
            names = ", ".join(str(path) for path in sidecars)
            raise OraclePrerequisiteError(
                f"remove stale PyBoy cartridge sidecars before running the oracle: {names}"
            )
        module = importlib.import_module("pyboy")
        pyboy_class = module.PyBoy
        self._pyboy = pyboy_class(
            str(artifacts.rom),
            symbols=str(artifacts.symbols),
            window="null",
            sound_emulated=False,
        )
        self._pyboy.set_emulation_speed(0)
        self._frame = 0
        self._checkpoints: dict[str, bytes] = {}

    @property
    def frame(self) -> int:
        return self._frame

    def tick(self, frames: int = 1) -> None:
        if frames < 0:
            raise OracleError("emulator frame count cannot be negative")
        if frames:
            self._pyboy.tick(frames, render=False, sound=False)
            self._frame += frames

    def press(self, button: str, hold_frames: int = 1, settle_frames: int = 1) -> None:
        if hold_frames < 1 or settle_frames < 0:
            raise OracleError("button timing requires hold >= 1 and settle >= 0 frames")
        self._pyboy.button_press(button)
        self.tick(hold_frames)
        self._pyboy.button_release(button)
        self.tick(settle_frames)

    def button_down(self, button: str) -> None:
        self._pyboy.button_press(button)

    def button_up(self, button: str) -> None:
        self._pyboy.button_release(button)

    def read(self, address: int) -> int:
        return cast(int, self._pyboy.memory[address])

    def register(self, name: str) -> int:
        """Expose CPU observations without offering a register mutation API."""
        if name not in {"A", "SP", "PC", "HL"}:
            raise OracleError(f"unsupported observed CPU register: {name}")
        return cast(int, getattr(self._pyboy.register_file, name))

    def save_checkpoint(self, name: str) -> None:
        stream = BytesIO()
        self._pyboy.save_state(stream)
        self._checkpoints[name] = stream.getvalue()

    def load_checkpoint(self, name: str) -> None:
        try:
            state = self._checkpoints[name]
        except KeyError as error:
            raise OracleError(f"unknown in-memory checkpoint: {name}") from error
        self._pyboy.load_state(BytesIO(state))

    def hook(self, bank: int, address: int, callback: Callable[[object], None]) -> None:
        self._pyboy.hook_register(bank, address, callback, None)

    def stop(self) -> None:
        self._pyboy.stop(save=False)


class OracleEmulator:
    def __init__(
        self,
        port: EmulatorPort,
        symbols: SymbolTable,
        metadata: SourceMetadata,
        world: WorldDefinition,
    ) -> None:
        self.port = port
        self.symbols = symbols
        self.metadata = metadata
        self.world = world
        self._last_input: str | None = None
        self._hook_hits: dict[str, int] = {}
        self._hooked_labels: set[str] = set()
        self._last_display_text_id: int | None = None
        self.observer: Callable[[SemanticState], None] | None = None

    def tick(self, frames: int = 1) -> None:
        if self.observer is None:
            self.port.tick(frames)
        else:
            for _ in range(frames):
                self.port.tick()
                self.observer(self.capture("observed-frame"))
        self._last_input = None

    def press(self, button: str, hold_frames: int = 1, settle_frames: int = 1) -> None:
        self._last_input = button
        if self.observer is None:
            self.port.press(button, hold_frames, settle_frames)
        else:
            self.button_down(button)
            self.tick(hold_frames)
            self.button_up(button)
            self.tick(settle_frames)

    def button_down(self, button: str) -> None:
        self._last_input = button
        self.port.button_down(button)

    def button_up(self, button: str) -> None:
        self.port.button_up(button)
        self._last_input = None

    def wait_until(
        self,
        label: str,
        predicate: Callable[[OracleEmulator], bool],
        *,
        max_frames: int,
        step_frames: int = 1,
    ) -> None:
        if max_frames < 1 or step_frames < 1:
            raise OracleError("bounded waits require positive frame limits")
        deadline = self.port.frame + max_frames
        while self.port.frame < deadline:
            if predicate(self):
                return
            self.tick(min(step_frames, deadline - self.port.frame))
        if predicate(self):
            return
        state = self.capture(f"timeout:{label}")
        raise OracleError(
            f"timed out after {max_frames} frames waiting for {label}; "
            f"frame={state.frame} map={state.map_id} player=({state.player_x},{state.player_y}) "
            f"facing={state.facing} walk={state.walk_counter} script={state.map_script} "
            f"joy_ignore={state.joy_ignore} simulated={state.simulated_joypad_index} "
            f"npc_index={state.npc_movement_index}"
        )

    def wait_for_symbol(self, label: str, *, max_frames: int) -> None:
        if max_frames < 1:
            raise OracleError("symbol waits require a positive frame limit")
        initial_hits = self._watch_symbol(label)
        deadline = self.port.frame + max_frames
        while self._hook_hits[label] == initial_hits and self.port.frame < deadline:
            self.tick()
        if self._hook_hits[label] == initial_hits:
            state = self.capture(f"timeout:{label}")
            raise OracleError(
                f"timed out after {max_frames} frames waiting for symbol {label}; "
                f"frame={state.frame} map={state.map_id} "
                f"player=({state.player_x},{state.player_y}) facing={state.facing} "
                f"script={state.map_script}"
            )

    def symbol_hits(self, label: str) -> int:
        """Return the number of observed calls, registering the hook if needed."""

        return self._watch_symbol(label)

    @property
    def last_display_text_id(self) -> int | None:
        return self._last_display_text_id

    def press_until_symbol(
        self,
        button: str,
        label: str,
        *,
        max_frames: int,
        hold_frames: int = 1,
        settle_frames: int = 1,
    ) -> None:
        if max_frames < 1 or hold_frames < 1 or settle_frames < 0:
            raise OracleError("bounded input waits require positive frame limits")
        initial_hits = self._watch_symbol(label)
        deadline = self.port.frame + max_frames
        while self._hook_hits[label] == initial_hits and self.port.frame < deadline:
            remaining = deadline - self.port.frame
            hold = min(hold_frames, remaining)
            settle = min(settle_frames, max(remaining - hold, 0))
            self.press(button, hold, settle)
        if self._hook_hits[label] == initial_hits:
            state = self.capture(f"timeout:{label}")
            raise OracleError(
                f"timed out after {max_frames} frames pressing {button} for symbol {label}; "
                f"frame={state.frame} map={state.map_id} "
                f"player=({state.player_x},{state.player_y}) facing={state.facing} "
                f"script={state.map_script}"
            )

    def _watch_symbol(self, label: str) -> int:
        if label not in self._hooked_labels:
            symbol = self.symbols[label]
            self._hook_hits[label] = 0

            def record_hit(_: object) -> None:
                self._hook_hits[label] += 1
                if label == "DisplayTextID":
                    self._last_display_text_id = self.port.read(self.symbols["hTextID"].address)

            self.port.hook(symbol.bank, symbol.address, record_hit)
            self._hooked_labels.add(label)
        return self._hook_hits[label]

    def save_checkpoint(self, name: str) -> None:
        self.port.save_checkpoint(name)

    def load_checkpoint(self, name: str) -> None:
        self.port.load_checkpoint(name)

    def capture(self, hook: str) -> SemanticState:
        map_id = self.metadata.map_name(self._read("wCurMap"))
        actors = self._actors(map_id)
        party_count = min(self._read("wPartyCount"), 6)
        party_base = self.symbols["wPartySpecies"].address
        party = tuple(
            species
            for offset in range(party_count)
            if (species := self.metadata.species_name(self.port.read(party_base + offset)))
            is not None
        )
        party_levels = (self._read("wPartyMon1Level"),) if party_count > 0 else ()
        event_base = self.symbols["wEventFlags"].address
        event_size = max(self.metadata.events.values(), default=0) // 8 + 1
        event_bytes = bytes(self.port.read(event_base + offset) for offset in range(event_size))
        player_state = self.symbols["wSpritePlayerStateData1"].address
        return SemanticState(
            frame=self.port.frame,
            hook=hook,
            input=self._last_input,
            map_id=map_id,
            player_x=self._read("wXCoord"),
            player_y=self._read("wYCoord"),
            facing=normalize_facing(self.port.read(player_state + 9)),
            walk_counter=self._read("wWalkCounter"),
            map_script=self._read("wCurMapScript"),
            joy_ignore=self._read("wJoyIgnore"),
            simulated_joypad_index=self._read("wSimulatedJoypadStatesIndex"),
            npc_movement_index=self._read("wNPCMovementDirections2Index"),
            actors=actors,
            flags=self.metadata.active_events(event_bytes),
            player_starter=self.metadata.species_name(self._read("wPlayerStarter")),
            rival_starter=self.metadata.species_name(self._read("wRivalStarter")),
            party=party,
            party_levels=party_levels,
            has_starter=bool(self._read("wStatusFlags4") & (1 << 3)),
        )

    def _read(self, label: str) -> int:
        return self.port.read(self.symbols[label].address)

    def _actors(self, map_id: str) -> tuple[ActorTrace, ...]:
        map_definition = self.world.maps.get(map_id)
        if map_definition is None:
            return ()
        state1 = self.symbols["wSpriteStateData1"].address
        state2 = self.symbols["wSpriteStateData2"].address
        actors: list[ActorTrace] = []
        for npc in map_definition.npcs:
            offset = npc.object_index * 16
            hidden = self._actor_hidden(npc.object_index)
            actors.append(
                ActorTrace(
                    id=npc.id,
                    x=self.port.read(state2 + offset + 5) - 4,
                    y=self.port.read(state2 + offset + 4) - 4,
                    facing=normalize_facing(self.port.read(state1 + offset + 9)),
                    visible=not hidden and self.port.read(state1 + offset) != 0,
                )
            )
        return tuple(actors)

    def _actor_hidden(self, object_index: int) -> bool:
        toggle_list = self.symbols["wToggleableObjectList"].address
        toggle_flags = self.symbols["wToggleableObjectFlags"].address
        for offset in range(0, 64, 2):
            sprite_id = self.port.read(toggle_list + offset)
            if sprite_id == 0xFF:
                return False
            flag_index = self.port.read(toggle_list + offset + 1)
            if sprite_id == object_index:
                return bool(
                    self.port.read(toggle_flags + flag_index // 8) & (1 << (flag_index % 8))
                )
        raise OracleError("toggleable object list has no sentinel")

    def stop(self) -> None:
        self.port.stop()
