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
from .emulator import OracleEmulator, PyBoyAdapter
from .errors import OracleError
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
    try:
        source_trace = run_scenario(
            NEW_GAME_SCENARIO,
            emulator,
            origin="pokered",
            source_revision=source.revision,
        )
    finally:
        emulator.stop()
    source_path = _write_trace(source_trace, paths)

    runtime = RuntimeAdapter(world, story)
    recorder = TraceRecorder(NEW_GAME_SCENARIO.id, "runtime", source.revision)
    recorder.record(runtime.capture("new-game-ready"))
    runtime_trace = recorder.finish()
    require_matching_traces(runtime_trace, source_trace)
    runtime_path = _write_trace(runtime_trace, paths)
    print(f"oracle traces: {source_path}, {runtime_path}")
    return 0


def main() -> None:
    try:
        raise SystemExit(run())
    except OracleError as error:
        print(f"oracle-check: {error}", file=sys.stderr)
        raise SystemExit(2) from error
