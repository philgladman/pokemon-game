from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from backend.app.source.pokered import PokeredSource

from .artifacts import (
    OraclePaths,
    build_artifacts,
    require_pyboy,
    resolve_rgbds,
    validate_artifacts,
)
from .battle_coverage import BattleCoverage, ObservedRandom
from .battle_observer import BattleObserver
from .battle_stats import validate_granted_starter
from .coverage import run_phase3a_coverage
from .emulator import OracleEmulator, PyBoyAdapter
from .errors import OracleError
from .gameplay import RuntimeGameplayDriver, SourceGameplayDriver, project_state
from .metadata import SourceMetadata
from .runtime import RuntimeAdapter
from .scenario import NEW_GAME_SCENARIO, run_scenario
from .symbols import SymbolTable
from .trace import SemanticTrace, TraceRecorder, require_matching_traces


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="python -m tools.pokered_oracle",
        description="Build and smoke-check the optional Pokémon Red reference oracle.",
    )
    result.add_argument(
        "command",
        choices=("doctor", "build", "check"),
        help="inspect prerequisites, build artifacts, or run the compatibility check",
    )
    result.add_argument("--source-root", type=Path)
    result.add_argument("--force-build", action="store_true")
    result.add_argument(
        "--battle",
        action="store_true",
        help="also compare live first-rival turns and win/loss outcomes for all starters",
    )
    result.add_argument(
        "--battle-stats",
        action="store_true",
        help="also compare granted starter stats/DVs/moves/PP against the Python battle factory",
    )
    return result


def _write_trace(trace: SemanticTrace, paths: OraclePaths) -> Path:
    path = paths.trace_path(trace.scenario, trace.origin)
    trace.write(path, paths.cache_root)
    return path


def doctor(paths: OraclePaths) -> int:
    source = PokeredSource(paths.source_root)
    source.build_story()
    print(f"source: ok ({source.revision})")
    resolve_rgbds()
    print("RGBDS: ok (1.0.4)")
    require_pyboy()
    print("PyBoy: ok (2.8.1)")
    try:
        cached = validate_artifacts(paths)
    except OracleError as error:
        print(f"cache: not reusable ({error}); build/check will replace it")
    else:
        print(f"cache: valid ({cached.sha1})")
    return 0


def run(argv: Sequence[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    project_root = Path(__file__).resolve().parents[2]
    paths = OraclePaths.defaults(project_root, arguments.source_root)
    if arguments.command == "doctor":
        return doctor(paths)
    artifacts = build_artifacts(paths, force=arguments.force_build)
    print(f"oracle ROM: {artifacts.rom} ({artifacts.sha1})")
    if arguments.command == "build":
        return 0
    require_pyboy()

    source = PokeredSource(paths.source_root)
    world = source.build_world()
    story = source.build_story()
    symbols = SymbolTable.read(artifacts.symbols)
    metadata = SourceMetadata.read(paths.source_root)
    adapter = PyBoyAdapter(artifacts)
    emulator = OracleEmulator(adapter, symbols, metadata, world)

    def starter_granted(species: str) -> None:
        validate_granted_starter(
            source.build_battle(),
            species,
            lambda label, offset: adapter.read(symbols[label].address + offset),
        )
        print(f"oracle battle stats: {species} matches observed DVs, stats, moves and PP")

    try:
        source_trace = run_scenario(
            NEW_GAME_SCENARIO,
            emulator,
            origin="pokered",
            source_revision=source.revision,
        )
        observer = BattleObserver(emulator, artifacts.rom) if arguments.battle else None
        rng = ObservedRandom(observer) if observer is not None else None
        definition = source.build_battle() if arguments.battle else None
        runtime = (
            RuntimeAdapter(world, story, definition, rng)
            if definition is not None
            else RuntimeAdapter(world, story)
        )
        battles = (
            BattleCoverage(
                SourceGameplayDriver(emulator, world), runtime, definition, observer, rng, paths
            )
            if definition is not None and observer is not None and rng is not None
            else None
        )
        recorder = TraceRecorder(NEW_GAME_SCENARIO.id, "runtime", source.revision)
        recorder.record(
            project_state(
                runtime.capture("new-game-ready"),
                "new-game-ready",
                (
                    "map_id",
                    "player_x",
                    "player_y",
                    "facing",
                    "actors",
                    "flags",
                    "party",
                    "party_levels",
                    "has_starter",
                ),
            )
        )
        runtime_trace = recorder.finish()
        _write_trace(source_trace, paths)
        _write_trace(runtime_trace, paths)
        require_matching_traces(runtime_trace, source_trace)

        coverage = run_phase3a_coverage(
            SourceGameplayDriver(emulator, world),
            RuntimeGameplayDriver(runtime, world),
            story,
            source.revision,
            lambda trace: _write_trace(trace, paths),
            on_starter_granted=starter_granted if arguments.battle_stats else None,
            on_starter_complete=battles.run_starter if battles is not None else None,
        )
    finally:
        emulator.stop()
    source_path = _write_trace(source_trace, paths)
    runtime_path = _write_trace(runtime_trace, paths)
    coverage_source_path = _write_trace(coverage.source, paths)
    coverage_runtime_path = _write_trace(coverage.runtime, paths)
    print(f"oracle boot traces: {source_path}, {runtime_path}")
    print(f"oracle coverage: {', '.join(coverage.scenarios)}")
    print(f"oracle coverage traces: {coverage_source_path}, {coverage_runtime_path}")
    return 0


def main() -> None:
    try:
        raise SystemExit(run())
    except OracleError as error:
        print(f"oracle-check: {error}", file=sys.stderr)
        raise SystemExit(2) from error
