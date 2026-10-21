"""Offline observer tests; these fixtures are not evidence of live ROM outcomes."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.pokered_oracle.artifacts import OraclePaths
from tools.pokered_oracle.battle_coverage import BattleCoverage, ObservedRandom
from tools.pokered_oracle.battle_observer import BattleObserver
from tools.pokered_oracle.errors import OracleError
from tools.pokered_oracle.symbols import Symbol, SymbolTable


class ReadOnlyPort:
    def __init__(self) -> None:
        self.memory: dict[int, int] = {}
        self.registers = {"SP": 0xDFFE, "A": 173}
        self.hooks: dict[tuple[int, int], Callable[[object], None]] = {}

    def read(self, address: int) -> int:
        return self.memory.get(address, 0)

    def register(self, name: str) -> int:
        return self.registers[name]

    def hook(self, bank: int, address: int, callback: Callable[[object], None]) -> None:
        assert (bank, address) not in self.hooks
        self.hooks[bank, address] = callback


def observer_fixture(tmp_path: Path) -> tuple[BattleObserver, ReadOnlyPort]:
    symbols = {
        "Random": Symbol(0, 0x1000),
        "Random_": Symbol(4, 0x7000),
        "Bankswitch": Symbol(0, 0x2000),
        "hRandomAdd": Symbol(0, 0xFFD3),
        "hLoadedROMBank": Symbol(0, 0xFFB8),
        "TrainerAI.getpointer": Symbol(14, 0x6000),
        "BattleRandom": Symbol(15, 0x7F00),
    }
    labels = (
        "DisplayUsedMoveText",
        "MainInBattleLoop",
        "HandlePlayerMonFainted",
        "HandleEnemyMonFainted",
        "HandleIfPlayerMoveMissed",
        "HandleIfEnemyMoveMissed",
        "MoveMissed",
        "CantLowerAnymore",
        "OaksLabRivalEndBattleScript",
        "SelectEnemyMove",
        "CriticalHitTest",
        "RandomizeDamage",
        "MoveHitTest",
        "StatModifierDownEffect",
        "PrintText",
    )
    symbols.update({label: Symbol(15, 0x4100 + i * 0x100) for i, label in enumerate(labels)})
    rom = bytearray(16 * 0x4000)
    rom[0x1000:0x1011] = bytes.fromhex("e5d5c50604210070cd0020f0d3c1d1e1c9")
    trainer_offset = 14 * 0x4000 + 0x2000
    rom[trainer_offset : trainer_offset + 7] = bytes.fromhex("2a666fcd0010e9")
    # A representative BattleRandom call after the SelectEnemyMove label.
    offset = 15 * 0x4000 + 0xA10
    rom[offset : offset + 3] = bytes.fromhex("cd007f")
    path = tmp_path / "fixture.gbc"
    path.write_bytes(rom)
    port = ReadOnlyPort()
    emulator = SimpleNamespace(port=port, symbols=SymbolTable(symbols))
    return BattleObserver(emulator, path), port


def random_return(observer: BattleObserver, port: ReadOnlyPort, bank: int, returned: int) -> None:
    port.memory[0xFFB8] = bank
    port.memory[0xDFFE] = returned & 255
    port.memory[0xDFFF] = returned >> 8
    port.hooks[0, 0x1010](None)


def test_random_observer_filters_frame_rng_and_preserves_actual_return_byte(tmp_path: Path) -> None:
    observer, port = observer_fixture(tmp_path)
    observer.active = True
    random_return(observer, port, 15, 0x4A13)
    random_return(observer, port, 0, 0x3200)  # Incidental frame/audio RNG.
    random_return(observer, port, 14, 0x6006)
    assert [(draw.reason, draw.value) for draw in observer.draws] == [
        ("SelectEnemyMove", 173),
        ("TrainerAI", 173),
    ]
    observer.reset()
    assert observer.draws == [] and observer.actions == [] and observer.boundary is None
    observer.active = False
    random_return(observer, port, 15, 0x4A13)
    assert observer.draws == []


def test_random_hook_refuses_rom_instruction_drift(tmp_path: Path) -> None:
    observer, _ = observer_fixture(tmp_path)
    path = tmp_path / "fixture.gbc"
    rom = bytearray(path.read_bytes())
    rom[0x1010] = 0
    path.write_bytes(rom)
    with pytest.raises(OracleError, match="Random implementation differs"):
        BattleObserver(observer.emulator, path)


def test_trainer_hook_refuses_rom_instruction_drift(tmp_path: Path) -> None:
    observer, _ = observer_fixture(tmp_path)
    path = tmp_path / "fixture.gbc"
    rom = bytearray(path.read_bytes())
    rom[14 * 0x4000 + 0x2000] = 0
    path.write_bytes(rom)
    with pytest.raises(OracleError, match="TrainerAI differs"):
        BattleObserver(observer.emulator, path)


def test_rng_grant_order_and_strict_replay_are_independent_of_optional_emulator() -> None:
    observer = SimpleNamespace(read=lambda label, offset: (0xAB, 0xCD)[offset])
    rng = ObservedRandom(observer)
    assert [rng(), rng()] == [0xCD, 0xAB]
    assert copy.deepcopy(rng) is rng
    rng.replay([12, 34])
    assert rng() == 12
    with pytest.raises(OracleError, match="unused"):
        rng.exhausted()
    assert rng() == 34
    rng.exhausted()
    with pytest.raises(OracleError, match="unobserved"):
        rng()


def test_mismatch_writes_both_partial_traces_before_failing(tmp_path: Path) -> None:
    paths = OraclePaths(tmp_path, tmp_path / "source", tmp_path / "cache")
    coverage = BattleCoverage(SimpleNamespace(world=None), None, None, None, None, paths)
    with pytest.raises(OracleError, match="battle mismatch at test/turn-1"):
        coverage._compare("test/turn-1", {"hp": 12}, {"hp": 11})
    for origin, hp in (("runtime", 12), ("pokered", 11)):
        payload = json.loads(paths.trace_path("phase-3b-live-battle", origin).read_text())
        assert payload["checkpoints"] == [
            {"checkpoint": "test/turn-1", "state": {"hp": hp}},
        ]
