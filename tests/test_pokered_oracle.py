from __future__ import annotations

import hashlib
import io
import subprocess
import sys
import tarfile
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.models.map import WorldDefinition
from tools.pokered_oracle import artifacts
from tools.pokered_oracle import cli as oracle_cli
from tools.pokered_oracle.artifacts import (
    OraclePaths,
    resolve_rgbds,
    stage_pinned_source,
    validate_artifacts,
    validate_canonical_hash_file,
)
from tools.pokered_oracle.emulator import OracleEmulator, PyBoyAdapter
from tools.pokered_oracle.errors import OracleError, OraclePrerequisiteError
from tools.pokered_oracle.metadata import SourceMetadata
from tools.pokered_oracle.scenario import Scenario, ScenarioStep, run_scenario
from tools.pokered_oracle.symbols import Symbol, SymbolTable
from tools.pokered_oracle.trace import (
    SemanticState,
    SemanticTrace,
    compare_traces,
    require_matching_traces,
)


def oracle_paths(tmp_path: Path) -> OraclePaths:
    source = tmp_path / "source"
    source.mkdir()
    return OraclePaths(tmp_path, source, tmp_path / ".cache/oracle")


def write_hash_file(source: Path, digest: str = artifacts.POKERED_RED_SHA1) -> None:
    (source / "roms.sha1").write_text(f"{digest} *pokered.gbc\n", encoding="utf-8")


def write_symbols(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            f"00:{0xC000 + index:04x} {name}\n"
            for index, name in enumerate(sorted(artifacts.REQUIRED_SYMBOLS))
        ),
        encoding="utf-8",
    )


def test_canonical_hash_file_rejects_source_drift(tmp_path: Path) -> None:
    paths = oracle_paths(tmp_path)
    write_hash_file(paths.source_root, "0" * 40)

    with pytest.raises(OracleError, match=r"canonical|drifted"):
        validate_canonical_hash_file(paths.source_root)


def test_artifacts_are_read_only_from_ignored_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = oracle_paths(tmp_path)
    payload = b"canonical-red-fixture"
    digest = hashlib.sha1(payload).hexdigest()
    monkeypatch.setattr(artifacts, "POKERED_RED_SHA1", digest)
    write_hash_file(paths.source_root, digest)
    paths.rom.parent.mkdir(parents=True)
    paths.rom.write_bytes(payload)
    write_symbols(paths.symbols)

    result = validate_artifacts(paths)

    assert result.rom == paths.cache_root / "build/pokered/pokered.gbc"
    assert result.sha1 == digest


def test_stage_pinned_source_extracts_archive_only_to_cache(tmp_path: Path) -> None:
    paths = oracle_paths(tmp_path)
    archive_bytes = io.BytesIO()
    with tarfile.open(fileobj=archive_bytes, mode="w") as archive:
        content = b"tracked\n"
        info = tarfile.TarInfo("Makefile")
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))

    def run(command: tuple[str, ...], **_: object) -> subprocess.CompletedProcess[bytes]:
        assert command[0:3] == ("git", "-C", str(paths.source_root))
        return subprocess.CompletedProcess(command, 0, archive_bytes.getvalue(), b"")

    stage_pinned_source(paths, run=run)

    assert (paths.build_root / "Makefile").read_text(encoding="utf-8") == "tracked\n"
    assert not (paths.source_root / "Makefile").exists()


def test_rgbds_requires_every_tool_at_exact_version(tmp_path: Path) -> None:
    for name in artifacts.RGBDS_TOOLS:
        (tmp_path / name).touch()

    def which(name: str) -> str:
        return str(tmp_path / name)

    def run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        version = "rgbds 1.0.3" if command[0].endswith("rgbfix") else "rgbds 1.0.4"
        return subprocess.CompletedProcess(command, 0, version, "")

    with pytest.raises(OracleError, match=r"rgbfix: expected 1\.0\.4"):
        resolve_rgbds(which=which, run=run)


def test_rgbds_rejects_version_with_matching_prefix(tmp_path: Path) -> None:
    for name in artifacts.RGBDS_TOOLS:
        (tmp_path / name).touch()

    def run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, "rgbds 1.0.40", "")

    with pytest.raises(OraclePrerequisiteError, match=r"expected 1\.0\.4"):
        resolve_rgbds(which=lambda name: str(tmp_path / name), run=run)


def test_rgbds_wraps_executable_failure(tmp_path: Path) -> None:
    for name in artifacts.RGBDS_TOOLS:
        (tmp_path / name).touch()

    def run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        raise OSError("not executable")

    with pytest.raises(OraclePrerequisiteError, match="unable to execute"):
        resolve_rgbds(which=lambda name: str(tmp_path / name), run=run)


def test_symbol_table_rejects_duplicates_and_reports_missing(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.sym"
    duplicate.write_text("00:c000 Label\n00:c001 Label\n", encoding="utf-8")
    with pytest.raises(OracleError, match="duplicate symbol"):
        SymbolTable.read(duplicate)

    symbols = tmp_path / "small.sym"
    symbols.write_text("00:c000 Present\n", encoding="utf-8")
    with pytest.raises(OracleError, match="Missing"):
        SymbolTable.read(symbols).require({"Present", "Missing"})


def test_symbol_table_accepts_real_rgbds_comments_and_spacing(tmp_path: Path) -> None:
    symbols = tmp_path / "pokered.sym"
    symbols.write_text(
        "; File generated by rgblink\n"
        "; bank:addr symbol\n"
        "  00:0150    EntryPoint ; optional inline comment\n"
        "01 MAP_OBJECT_CONSTANT\n"
        "01:4000 BankedSymbol\n",
        encoding="utf-8",
    )

    table = SymbolTable.read(symbols)

    assert table["EntryPoint"] == Symbol(bank=0, address=0x0150)
    assert table["BankedSymbol"] == Symbol(bank=1, address=0x4000)


class FakePyBoy:
    def __init__(self, rom: str, **options: object) -> None:
        self.rom = rom
        self.options = options
        self.memory = bytearray(0x10000)
        self.calls: list[object] = []

    def set_emulation_speed(self, speed: int) -> None:
        self.calls.append(("speed", speed))

    def tick(self, frames: int, **options: object) -> None:
        self.calls.append(("tick", frames, options))

    def button_press(self, button: str) -> None:
        self.calls.append(("press", button))

    def button_release(self, button: str) -> None:
        self.calls.append(("release", button))

    def save_state(self, stream: io.BytesIO) -> None:
        stream.write(b"state")

    def load_state(self, stream: io.BytesIO) -> None:
        self.calls.append(("load", stream.read()))

    def hook_register(self, bank: int, address: int, callback: object, context: object) -> None:
        self.calls.append(("hook", bank, address, callback, context))

    def stop(self, *, save: bool) -> None:
        self.calls.append(("stop", save))


def test_pyboy_adapter_is_headless_and_keeps_checkpoints_in_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = oracle_paths(tmp_path)
    paths.rom.parent.mkdir(parents=True)
    paths.rom.write_bytes(b"rom")
    paths.symbols.write_text("00:c000 Label\n", encoding="utf-8")
    fake = FakePyBoy
    monkeypatch.setattr("tools.pokered_oracle.emulator.require_pyboy", lambda: None)
    monkeypatch.setattr(
        "tools.pokered_oracle.emulator.importlib.import_module",
        lambda _: SimpleNamespace(PyBoy=fake),
    )

    adapter = PyBoyAdapter(artifacts.BuildArtifacts(paths.rom, paths.symbols, "hash", True))
    adapter.press("a", hold_frames=2, settle_frames=3)
    adapter.save_checkpoint("ready")
    adapter.load_checkpoint("ready")
    adapter.stop()

    pyboy = adapter._pyboy
    assert pyboy.options == {
        "symbols": str(paths.symbols),
        "window": "null",
        "sound_emulated": False,
    }
    assert adapter.frame == 5
    assert ("load", b"state") in pyboy.calls
    assert not list(paths.cache_root.rglob("*.state"))


def test_pyboy_adapter_rejects_unknown_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = oracle_paths(tmp_path)
    paths.rom.parent.mkdir(parents=True)
    paths.rom.write_bytes(b"rom")
    paths.symbols.write_text("00:c000 Label\n", encoding="utf-8")
    monkeypatch.setattr("tools.pokered_oracle.emulator.require_pyboy", lambda: None)
    monkeypatch.setattr(
        "tools.pokered_oracle.emulator.importlib.import_module",
        lambda _: SimpleNamespace(PyBoy=FakePyBoy),
    )
    adapter = PyBoyAdapter(artifacts.BuildArtifacts(paths.rom, paths.symbols, "hash", True))

    with pytest.raises(OracleError, match="unknown in-memory checkpoint"):
        adapter.load_checkpoint("missing")


@pytest.mark.parametrize("suffix", [".ram", ".rtc"])
def test_pyboy_adapter_rejects_stale_cartridge_sidecars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, suffix: str
) -> None:
    paths = oracle_paths(tmp_path)
    paths.rom.parent.mkdir(parents=True)
    paths.rom.write_bytes(b"rom")
    paths.rom.with_suffix(suffix).write_bytes(b"stale")
    paths.symbols.write_text("00:c000 Label\n", encoding="utf-8")
    monkeypatch.setattr("tools.pokered_oracle.emulator.require_pyboy", lambda: None)

    with pytest.raises(OraclePrerequisiteError, match="stale PyBoy cartridge sidecars"):
        PyBoyAdapter(artifacts.BuildArtifacts(paths.rom, paths.symbols, "hash", True))


class NeverHookPort:
    def __init__(self) -> None:
        self.frame = 0

    def tick(self, frames: int = 1) -> None:
        self.frame += frames

    def press(self, button: str, hold_frames: int = 1, settle_frames: int = 1) -> None:
        del button
        self.frame += hold_frames + settle_frames

    def read(self, address: int) -> int:
        del address
        return 0

    def save_checkpoint(self, name: str) -> None:
        del name

    def load_checkpoint(self, name: str) -> None:
        del name

    def hook(self, bank: int, address: int, callback: Callable[[object], None]) -> None:
        del bank, address, callback

    def stop(self) -> None:
        pass


def test_symbol_timeout_reports_normalized_state() -> None:
    symbols = SymbolTable(
        {name: Symbol(0, 0xC000 + index) for index, name in enumerate(artifacts.REQUIRED_SYMBOLS)}
    )
    emulator = OracleEmulator(
        NeverHookPort(),
        symbols,
        SourceMetadata({}, {}, {}),
        WorldDefinition.model_construct(maps={}),
    )

    with pytest.raises(
        OracleError,
        match=r"frame=1 map=MAP_00 player=\(0,0\) facing=south script=0",
    ):
        emulator.wait_for_symbol("PrepareTitleScreen", max_frames=1)


class FakeScenarioDriver:
    def __init__(self) -> None:
        self.frame = 0
        self.actions: list[str] = []

    def tick(self, frames: int = 1) -> None:
        self.frame += frames
        self.actions.append(f"tick:{frames}")

    def press(self, button: str, hold_frames: int = 1, settle_frames: int = 1) -> None:
        self.frame += hold_frames + settle_frames
        self.actions.append(f"press:{button}:{hold_frames}:{settle_frames}")

    def wait_for_symbol(self, label: str, *, max_frames: int) -> None:
        self.frame += 1
        self.actions.append(f"wait:{label}:{max_frames}")

    def press_until_symbol(
        self,
        button: str,
        label: str,
        *,
        max_frames: int,
        hold_frames: int = 1,
        settle_frames: int = 1,
    ) -> None:
        self.frame += hold_frames + settle_frames
        self.actions.append(
            f"press-until:{button}:{label}:{max_frames}:{hold_frames}:{settle_frames}"
        )

    def capture(self, hook: str) -> SemanticState:
        self.actions.append(f"capture:{hook}")
        return SemanticState(frame=self.frame, hook=hook, map_id="PALLET_TOWN")


def test_scenario_runner_is_ordered_and_deterministic() -> None:
    scenario = Scenario(
        "fixture",
        (
            ScenarioStep("tick", "warm-up", frames=3),
            ScenarioStep("press", "confirm", button="a", hold_frames=2, settle_frames=1),
            ScenarioStep("wait_symbol", "OverworldLoop", frames=90),
            ScenarioStep("capture", "ready"),
        ),
    )
    driver = FakeScenarioDriver()

    trace = run_scenario(scenario, driver, origin="pokered", source_revision="a" * 40)

    assert driver.actions == [
        "tick:3",
        "press:a:2:1",
        "wait:OverworldLoop:90",
        "capture:ready",
    ]
    assert trace.states == (SemanticState(frame=7, hook="ready", map_id="PALLET_TOWN"),)


@pytest.mark.parametrize(
    "step,message",
    [
        (ScenarioStep("tick", "valid"), None),
    ],
)
def test_scenario_step_fixture_is_valid(step: ScenarioStep, message: str | None) -> None:
    assert step.label == "valid"
    assert message is None


def test_scenario_validation_rejects_invalid_steps() -> None:
    with pytest.raises(OracleError, match="require a button"):
        ScenarioStep("press", "bad")
    with pytest.raises(OracleError, match="cannot specify a button"):
        ScenarioStep("tick", "bad", button="a")
    with pytest.raises(OracleError, match="duplicate capture"):
        Scenario("bad", (ScenarioStep("capture", "same"), ScenarioStep("capture", "same")))


def test_trace_comparison_ignores_frames_and_wildcard_fields() -> None:
    expected = SemanticTrace(
        "fixture",
        "runtime",
        "a" * 40,
        (SemanticState(frame=1, hook="ready", map_id="PALLET_TOWN", walk_counter=None),),
    )
    actual = SemanticTrace(
        "fixture",
        "pokered",
        "a" * 40,
        (SemanticState(frame=900, hook="ready", map_id="PALLET_TOWN", walk_counter=7),),
    )

    assert compare_traces(expected, actual) == ()
    assert compare_traces(expected, actual, compare_frames=True)[0].field == "frame"


def test_trace_mismatch_has_actionable_field_path() -> None:
    expected = SemanticTrace(
        "fixture",
        "runtime",
        "a" * 40,
        (SemanticState(frame=0, hook="ready", facing="north"),),
    )
    actual = SemanticTrace(
        "fixture",
        "pokered",
        "a" * 40,
        (SemanticState(frame=0, hook="ready", facing="south"),),
    )

    with pytest.raises(OracleError, match=r"state\[0\]\.facing"):
        require_matching_traces(expected, actual)


def test_trace_write_refuses_paths_outside_cache(tmp_path: Path) -> None:
    trace = SemanticTrace("fixture", "runtime", "a" * 40, ())
    with pytest.raises(OracleError, match="must stay under"):
        trace.write(tmp_path / "trace.json", tmp_path / "cache")


class FakeSource:
    revision = "a" * 40

    def build_world(self) -> object:
        return object()

    def build_story(self) -> object:
        return object()


class FakeEmulator:
    def stop(self) -> None:
        pass


class FakeRuntime:
    def __init__(self, world: object, story: object) -> None:
        del world, story

    def capture(self, hook: str) -> SemanticState:
        return SemanticState(
            frame=0,
            hook=hook,
            map_id="REDS_HOUSE_2F",
            player_x=3,
            player_y=6,
            facing="north",
            actors=(),
            flags=(),
            party=(),
        )


def configure_cli_fakes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, source_facing: str = "north"
) -> None:
    fake_artifacts = artifacts.BuildArtifacts(
        tmp_path / "pokered.gbc", tmp_path / "pokered.sym", artifacts.POKERED_RED_SHA1, True
    )
    monkeypatch.setattr(oracle_cli, "build_artifacts", lambda *args, **kwargs: fake_artifacts)
    monkeypatch.setattr(oracle_cli, "require_pyboy", lambda: None)
    monkeypatch.setattr(oracle_cli, "PokeredSource", lambda _: FakeSource())
    monkeypatch.setattr("tools.pokered_oracle.cli.SymbolTable.read", lambda _: object())
    monkeypatch.setattr("tools.pokered_oracle.cli.SourceMetadata.read", lambda _: object())
    monkeypatch.setattr(oracle_cli, "PyBoyAdapter", lambda _: object())
    monkeypatch.setattr(oracle_cli, "OracleEmulator", lambda *args: FakeEmulator())
    monkeypatch.setattr(oracle_cli, "RuntimeAdapter", FakeRuntime)
    source_trace = SemanticTrace(
        "new-game-ready",
        "pokered",
        "a" * 40,
        (
            SemanticState(
                frame=1_000,
                hook="new-game-ready",
                map_id="REDS_HOUSE_2F",
                player_x=3,
                player_y=6,
                facing=source_facing,
                actors=(),
                flags=(),
                party=(),
            ),
        ),
    )
    monkeypatch.setattr(oracle_cli, "run_scenario", lambda *args, **kwargs: source_trace)
    monkeypatch.setattr(
        oracle_cli,
        "_write_trace",
        lambda trace, paths: paths.cache_root / f"{trace.origin}.json",
    )


def test_cli_check_compares_common_new_game_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_cli_fakes(monkeypatch, tmp_path)

    assert oracle_cli.run(["check", "--source-root", str(tmp_path)]) == 0


def test_cli_check_fails_on_semantic_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_cli_fakes(monkeypatch, tmp_path, source_facing="south")

    with pytest.raises(OracleError, match=r"state\[0\]\.facing"):
        oracle_cli.run(["check", "--source-root", str(tmp_path)])


def test_cli_main_returns_nonzero_on_semantic_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    configure_cli_fakes(monkeypatch, tmp_path, source_facing="south")
    monkeypatch.setattr(
        sys,
        "argv",
        ["pokered_oracle", "check", "--source-root", str(tmp_path)],
    )

    with pytest.raises(SystemExit) as exit_info:
        oracle_cli.main()

    assert exit_info.value.code == 2
    assert "semantic trace mismatch" in capsys.readouterr().err


def test_cli_doctor_is_read_only_and_allows_missing_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(oracle_cli, "PokeredSource", lambda _: FakeSource())
    monkeypatch.setattr(oracle_cli, "resolve_rgbds", lambda: object())
    monkeypatch.setattr(oracle_cli, "require_pyboy", lambda: None)
    monkeypatch.setattr(
        oracle_cli,
        "validate_artifacts",
        lambda _: (_ for _ in ()).throw(OracleError("missing oracle ROM")),
    )

    assert oracle_cli.run(["doctor", "--source-root", str(tmp_path)]) == 0
    assert not (tmp_path / ".cache").exists()
    output = capsys.readouterr().out
    assert "source: ok" in output
    assert "RGBDS: ok (1.0.4)" in output
    assert "PyBoy: ok (2.8.1)" in output
    assert "cache: not reusable" in output


def test_cli_doctor_returns_nonzero_for_bad_prerequisite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(oracle_cli, "PokeredSource", lambda _: FakeSource())
    monkeypatch.setattr(
        oracle_cli,
        "resolve_rgbds",
        lambda: (_ for _ in ()).throw(OraclePrerequisiteError("wrong RGBDS")),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["pokered_oracle", "doctor", "--source-root", str(tmp_path)],
    )

    with pytest.raises(SystemExit) as exit_info:
        oracle_cli.main()

    assert exit_info.value.code == 2
    assert "wrong RGBDS" in capsys.readouterr().err
