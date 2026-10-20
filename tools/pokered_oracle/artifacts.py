from __future__ import annotations

import hashlib
import importlib.metadata
import io
import os
import re
import shutil
import subprocess
import tarfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from backend.app.source.pokered import PokeredSource
from backend.app.source.pokered.source import PINNED_REVISION

from .errors import OracleError, OraclePrerequisiteError
from .symbols import SymbolTable

PYBOY_VERSION = "2.8.1"
RGBDS_VERSION = "1.0.4"
POKERED_RED_SHA1 = "ea9bcae617fdf159b045185467ae58b2e4a48b9a"
RGBDS_TOOLS = ("rgbasm", "rgblink", "rgbfix", "rgbgfx")
REQUIRED_SYMBOLS = {
    "wCurMap",
    "wXCoord",
    "wYCoord",
    "wSpritePlayerStateData1",
    "wSpriteStateData1",
    "wSpriteStateData2",
    "wWalkCounter",
    "wPlayerMovingDirection",
    "wCurMapScript",
    "wJoyIgnore",
    "wSimulatedJoypadStatesIndex",
    "wNPCMovementDirections2Index",
    "wEventFlags",
    "wPartyCount",
    "wPartySpecies",
    "wPartyMon1Level",
    "wPlayerStarter",
    "wRivalStarter",
    "wStatusFlags4",
    "wToggleableObjectFlags",
    "wToggleableObjectList",
    "hTextID",
    "DisplayTextID",
    "PrepareTitleScreen",
    "MainMenu",
    "StartNewGame",
    "ChoosePlayerName",
    "ChooseRivalName",
    "HandleMenuInput",
    "OverworldLoop",
    "JoypadOverworld",
    "YesNoChoice",
}

RunCommand = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class OraclePaths:
    project_root: Path
    source_root: Path
    cache_root: Path

    @classmethod
    def defaults(cls, project_root: Path, source_root: Path | None = None) -> OraclePaths:
        root = project_root.resolve()
        return cls(
            project_root=root,
            source_root=(source_root or root / "external/pokered").resolve(),
            cache_root=(root / ".cache/oracle").resolve(),
        )

    @property
    def rom(self) -> Path:
        return self.build_root / "pokered.gbc"

    @property
    def symbols(self) -> Path:
        return self.build_root / "pokered.sym"

    @property
    def build_root(self) -> Path:
        return self.cache_root / "build" / "pokered"

    def trace_path(self, scenario_id: str, origin: str) -> Path:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", scenario_id):
            raise OracleError(f"invalid scenario id for trace path: {scenario_id!r}")
        if origin not in {"pokered", "runtime"}:
            raise OracleError(f"invalid trace origin: {origin!r}")
        path = (self.cache_root / "traces" / f"{scenario_id}-{origin}.json").resolve()
        if self.cache_root not in path.parents:
            raise OracleError(f"trace path escapes oracle cache: {path}")
        return path


@dataclass(frozen=True)
class Toolchain:
    tools: Mapping[str, Path]


@dataclass(frozen=True)
class BuildArtifacts:
    rom: Path
    symbols: Path
    sha1: str
    reused: bool


def pyboy_version() -> str:
    try:
        return importlib.metadata.version("pyboy")
    except importlib.metadata.PackageNotFoundError as error:
        raise OraclePrerequisiteError(
            f"PyBoy {PYBOY_VERSION} is required; install with .venv/bin/pip install -e '.[oracle]'"
        ) from error


def require_pyboy() -> None:
    installed = pyboy_version()
    if installed != PYBOY_VERSION:
        raise OraclePrerequisiteError(f"PyBoy {PYBOY_VERSION} is required; found {installed}")


def resolve_rgbds(
    environ: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
    run: RunCommand = subprocess.run,
) -> Toolchain:
    environment = os.environ if environ is None else environ
    prefix = environment.get("RGBDS", "")
    resolved: dict[str, Path] = {}
    problems: list[str] = []
    for name in RGBDS_TOOLS:
        candidate = f"{prefix}{name}" if prefix else which(name)
        if candidate is None or not Path(candidate).is_file():
            problems.append(f"{name}: not found")
            continue
        try:
            result = run(
                [candidate, "--version"],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError as error:
            problems.append(f"{name}: unable to execute ({error})")
            continue
        output = f"{result.stdout}\n{result.stderr}"
        version_match = re.search(r"(?<![0-9.])v?(\d+\.\d+\.\d+)(?![0-9.])", output)
        version = None if version_match is None else version_match.group(1)
        if result.returncode != 0 or version != RGBDS_VERSION:
            version = output.strip() or f"exit {result.returncode}"
            problems.append(f"{name}: expected {RGBDS_VERSION}, found {version}")
            continue
        resolved[name] = Path(candidate).resolve()
    if problems:
        raise OraclePrerequisiteError("RGBDS 1.0.4 prerequisites failed: " + "; ".join(problems))
    return Toolchain(tools=resolved)


def validate_canonical_hash_file(source_root: Path) -> None:
    hashes = source_root / "roms.sha1"
    if not hashes.is_file():
        raise OracleError(f"missing canonical ROM hashes: {hashes}")
    for line in hashes.read_text(encoding="utf-8").splitlines():
        digest, separator, filename = line.partition(" ")
        if separator and filename.lstrip(" *") == "pokered.gbc":
            if not re.fullmatch(r"[0-9a-f]{40}", digest):
                break
            if digest != POKERED_RED_SHA1:
                raise OracleError(
                    "pinned source pokered.gbc SHA-1 drifted: "
                    f"expected {POKERED_RED_SHA1}, found {digest}"
                )
            return
    raise OracleError(f"roms.sha1 has no valid pokered.gbc SHA-1: {hashes}")


def validate_artifacts(paths: OraclePaths) -> BuildArtifacts:
    if not paths.rom.is_file():
        raise OracleError(f"missing oracle ROM: {paths.rom}")
    validate_canonical_hash_file(paths.source_root)
    actual = hashlib.sha1(paths.rom.read_bytes()).hexdigest()
    if actual != POKERED_RED_SHA1:
        raise OracleError(
            f"pokered.gbc SHA-1 mismatch: expected {POKERED_RED_SHA1}, found {actual}"
        )
    symbols = SymbolTable.read(paths.symbols)
    symbols.require(REQUIRED_SYMBOLS)
    return BuildArtifacts(paths.rom, paths.symbols, actual, reused=True)


def stage_pinned_source(
    paths: OraclePaths,
    *,
    run: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
) -> None:
    """Export only pinned tracked files into the ignored build cache."""

    command = (
        "git",
        "-C",
        str(paths.source_root),
        "archive",
        "--format=tar",
        PINNED_REVISION,
    )
    try:
        result = run(command, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as error:
        raise OracleError(
            f"unable to export pinned pret/pokered source: {' '.join(command)}"
        ) from error

    build_root = paths.build_root
    if build_root.exists():
        shutil.rmtree(build_root)
    build_root.mkdir(parents=True)
    try:
        with tarfile.open(fileobj=io.BytesIO(result.stdout), mode="r:") as archive:
            archive.extractall(build_root, filter="data")
    except (tarfile.TarError, OSError) as error:
        raise OracleError("pinned pret/pokered archive could not be extracted") from error


def build_artifacts(
    paths: OraclePaths,
    *,
    force: bool = False,
    environ: Mapping[str, str] | None = None,
    run: RunCommand = subprocess.run,
) -> BuildArtifacts:
    PokeredSource(paths.source_root).build_story()
    toolchain = resolve_rgbds(environ=environ, run=run)
    if not force:
        try:
            return validate_artifacts(paths)
        except OracleError:
            pass
    stage_pinned_source(paths)
    command: Sequence[str] = (
        "make",
        "-B",
        "-C",
        str(paths.build_root),
        "DEBUG=1",
        "red",
    )
    build_environment = dict(os.environ if environ is None else environ)
    build_environment.update(
        {
            "RGBASM": str(toolchain.tools["rgbasm"]),
            "RGBLINK": str(toolchain.tools["rgblink"]),
            "RGBFIX": str(toolchain.tools["rgbfix"]),
            "RGBGFX": str(toolchain.tools["rgbgfx"]),
        }
    )
    try:
        run(command, check=True, text=True, env=build_environment)
    except (OSError, subprocess.CalledProcessError) as error:
        raise OracleError(f"pret/pokered debug build failed: {' '.join(command)}") from error
    validated = validate_artifacts(paths)
    return BuildArtifacts(validated.rom, validated.symbols, validated.sha1, reused=False)
