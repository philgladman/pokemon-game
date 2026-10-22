from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from sameboy import run
from sameboy.audio import MAX_CLIENTS, AudioBridge
from sameboy.run import StartupCancelled, stop_process, wait_ready


@pytest.mark.parametrize("listening", [True, False])
def test_health_checks_browser_port(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, listening: bool
) -> None:
    ready = tmp_path / "ready.json"
    ready.write_text("[123]")
    monkeypatch.setattr(run, "READY", ready)
    monkeypatch.setattr(run.os, "kill", lambda _pid, _signal: None)
    checked_ports: list[int] = []

    def browser_ready(port: int) -> bool:
        checked_ports.append(port)
        return listening

    monkeypatch.setattr(run, "tcp_ready", browser_ready)
    assert run.health() is listening
    assert checked_ports == [8080]


def test_readiness_detects_failed_dependency() -> None:
    process = subprocess.Popen([sys.executable, "-c", "raise SystemExit(3)"])
    process.wait(timeout=3)
    with pytest.raises(RuntimeError, match="code=3"):
        wait_ready(lambda: True, [process], timeout=1)


def test_readiness_is_bounded() -> None:
    with pytest.raises(TimeoutError):
        wait_ready(lambda: False, [], timeout=0.01)


def test_requested_stop_cancels_even_an_already_ready_startup() -> None:
    with pytest.raises(StartupCancelled):
        wait_ready(lambda: True, [], cancelled=lambda: True)


@pytest.mark.parametrize("exit_code", [1, -15])
def test_failed_sdl_quit_cannot_report_confirmed_save_flush(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, exit_code: int
) -> None:
    process = subprocess.Popen([sys.executable, "-c", f"raise SystemExit({abs(exit_code)})"])
    process.wait(timeout=3)
    monkeypatch.setattr(run, "close_window", lambda _pid: None)
    # An unsuccessful emulator exit must be treated as unconfirmed even if the
    # window-close request itself succeeded.
    monkeypatch.setattr(process, "wait", lambda **_kwargs: exit_code)
    assert run.stop_emulator(process) is False
    assert "save_flush=unconfirmed" in caplog.text
    assert "outcome=graceful" not in caplog.text


def test_sdl_quit_failure_forces_and_reaps_emulator(monkeypatch: pytest.MonkeyPatch) -> None:
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])

    def missing_window(_pid: int) -> None:
        raise RuntimeError("window not found")

    monkeypatch.setattr(run, "close_window", missing_window)
    assert run.stop_emulator(process) is False
    assert process.poll() is not None


def test_successful_sdl_quit_confirms_graceful_exit(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait(timeout=3)
    monkeypatch.setattr(run, "close_window", lambda _pid: None)
    with caplog.at_level("INFO"):
        assert run.stop_emulator(process) is True
    assert "outcome=graceful" in caplog.text
    assert "save_flush=unconfirmed" not in caplog.text


def test_shutdown_reaps_process() -> None:
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    stop_process(process)
    assert process.poll() is not None
    stop_process(process)


@pytest.mark.parametrize("failure", ["missing_rom", "invalid_model", "occupied_profile"])
def test_invalid_runtime_inputs_fail_before_starting_services(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: str
) -> None:
    rom = tmp_path / "rom" / "pokered.gbc"
    rom.parent.mkdir()
    if failure != "missing_rom":
        rom.write_bytes(bytes(0x150))
    profile = tmp_path / "profile"
    profile.mkdir()
    if failure == "occupied_profile":
        (profile / "game.gb").write_text("unmanaged user file")
    monkeypatch.setattr(run, "Path", lambda name: tmp_path / str(name).lstrip("/"))
    monkeypatch.setattr(run, "READY", tmp_path / "ready.json")
    monkeypatch.setattr(run.signal, "signal", lambda *_args: None)
    monkeypatch.setenv("SAMEBOY_MODEL", "invalid" if failure == "invalid_model" else "cgb-e")
    monkeypatch.setenv("SAMEBOY_ROM", "/rom/pokered.gbc")

    def unexpected_process(*_args: Any, **_kwargs: Any) -> None:
        pytest.fail("invalid input started a runtime service")

    monkeypatch.setattr(run.subprocess, "Popen", unexpected_process)
    assert run.main() == 1
    assert not run.READY.exists()
    if failure == "occupied_profile":
        assert (profile / "game.gb").read_text() == "unmanaged user file"


def test_stop_during_startup_reaps_started_child_and_never_publishes_health(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rom = tmp_path / "rom" / "pokered.gbc"
    rom.parent.mkdir()
    rom.write_bytes(bytes(0x150))
    (tmp_path / "profile").mkdir()
    monkeypatch.setattr(run, "Path", lambda name: tmp_path / str(name).lstrip("/"))
    monkeypatch.setattr(run, "READY", tmp_path / "ready.json")
    monkeypatch.setenv("SAMEBOY_MODEL", "cgb-e")
    monkeypatch.setenv("SAMEBOY_ROM", "/rom/pokered.gbc")
    handlers: dict[int, Any] = {}
    monkeypatch.setattr(
        run.signal, "signal", lambda number, handler: handlers.update({number: handler})
    )
    original_popen = subprocess.Popen
    children: list[subprocess.Popen[bytes]] = []

    def start_child(*_args: Any, **_kwargs: Any) -> subprocess.Popen[bytes]:
        child = original_popen([sys.executable, "-c", "import time; time.sleep(30)"])
        children.append(child)
        return child

    def stop_before_ready(check: Any, processes: Any, **kwargs: Any) -> None:
        handlers[run.signal.SIGTERM](run.signal.SIGTERM, None)
        wait_ready(check, processes, **kwargs)

    monkeypatch.setattr(run.subprocess, "Popen", start_child)
    monkeypatch.setattr(run, "wait_ready", stop_before_ready)
    assert run.main() == 0
    assert len(children) == 1
    assert children[0].poll() is not None
    assert not run.READY.exists()


class AudioClient:
    def __init__(self, slow: bool = False) -> None:
        self.slow = slow
        self.frames: list[bytes] = []
        self.closed = False

    async def send(self, pcm: bytes) -> None:
        if self.slow:
            await asyncio.sleep(10)
        self.frames.append(pcm)

    async def close(self, **_kwargs: Any) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        await asyncio.sleep(0)


def test_audio_fanout_disconnects_slow_client_without_losing_fast_audio() -> None:
    async def scenario() -> None:
        bridge = AudioBridge()
        fast, slow = AudioClient(), AudioClient(slow=True)
        bridge.clients.update([fast, slow])  # type: ignore[arg-type]
        await asyncio.wait_for(bridge.broadcast(b"\x01\x00" * 1920), timeout=1)
        assert fast.frames == [b"\x01\x00" * 1920]
        assert slow.closed
        assert slow not in bridge.clients
        await bridge.broadcast(b"next")
        assert fast.frames[-1] == b"next"

    asyncio.run(scenario())


def test_audio_clients_are_bounded_and_disconnect_releases_capacity() -> None:
    async def scenario() -> None:
        bridge = AudioBridge()
        bridge.clients.update(AudioClient() for _ in range(MAX_CLIENTS))  # type: ignore[arg-type]
        rejected = AudioClient()
        await bridge.connect(rejected)  # type: ignore[arg-type]
        assert rejected.closed
        assert len(bridge.clients) == MAX_CLIENTS
        bridge.clients.clear()
        reconnected = AudioClient()
        await bridge.connect(reconnected)  # type: ignore[arg-type]
        assert not reconnected.closed
        assert not bridge.clients

    asyncio.run(scenario())
