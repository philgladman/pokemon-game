"""Own and supervise the private emulator, display, audio and browser transports."""

from __future__ import annotations

import json
import logging
import os
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("sameboy.runtime")
READY = Path("/tmp/sameboy-ready.json")


class StartupCancelled(Exception):
    """A normal stop was requested before startup completed."""


def wait_ready(
    check: Callable[[], bool],
    processes: list[subprocess.Popen[bytes]],
    timeout: float = 15,
    cancelled: Callable[[], bool] = lambda: False,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cancelled():
            raise StartupCancelled
        for process in processes:
            if process.poll() is not None:
                raise RuntimeError(
                    f"required process exited pid={process.pid} code={process.returncode}"
                )
        if check():
            return
        time.sleep(0.1)
    raise TimeoutError("service readiness deadline exceeded")


def tcp_ready(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            return True
    except OSError:
        return False


def command_ready(*args: str) -> bool:
    try:
        return (
            subprocess.run(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=1,
                check=False,
            ).returncode
            == 0
        )
    except subprocess.TimeoutExpired:
        return False


def close_window(pid: int) -> None:
    # SDL handles WM_DELETE_WINDOW as SDL_QUIT, flushing battery RAM before exit.
    # SIGTERM alone bypasses that upstream path.
    from Xlib import X, display, protocol  # type: ignore[import-untyped]

    connection = display.Display()
    try:
        pid_atom = connection.intern_atom("_NET_WM_PID")
        delete_atom = connection.intern_atom("WM_DELETE_WINDOW")
        for window in connection.screen().root.query_tree().children:
            prop = window.get_full_property(pid_atom, X.AnyPropertyType)
            if (
                prop is not None
                and int(prop.value[0]) == pid
                and delete_atom in (window.get_wm_protocols() or [])
            ):
                event = protocol.event.ClientMessage(
                    window=window,
                    client_type=connection.intern_atom("WM_PROTOCOLS"),
                    data=(32, [delete_atom, X.CurrentTime, 0, 0, 0]),
                )
                window.send_event(event, event_mask=0)
                connection.sync()
                return
        raise RuntimeError("SameBoy SDL window not found")
    finally:
        connection.close()


def stop_process(process: subprocess.Popen[bytes], timeout: float = 2) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


def stop_emulator(emulator: subprocess.Popen[bytes]) -> bool:
    try:
        close_window(emulator.pid)
        code = emulator.wait(timeout=10)
        if code != 0:
            raise RuntimeError(f"SameBoy quit failed code={code}")
        LOGGER.info("event=emulator_stopped outcome=graceful")
        return True
    except Exception:
        LOGGER.exception("event=emulator_stopped outcome=forced save_flush=unconfirmed")
        stop_process(emulator)
        return False


def health() -> bool:
    try:
        pids = json.loads(READY.read_text())
        for pid in pids:
            os.kill(pid, 0)
        # The supervisor watches all children; avoid opening fake WebSocket/VNC
        # sessions on every health check, which produces handshake error logs.
        return tcp_ready(8081)
    except (OSError, ValueError):
        return False


def main() -> int:
    processes: list[subprocess.Popen[bytes]] = []
    emulator: subprocess.Popen[bytes] | None = None
    stopping = False
    result = 0

    def request_stop(_signal: int, _frame: Any) -> None:
        nonlocal stopping
        stopping = True

    def start(name: str, *args: str) -> subprocess.Popen[bytes]:
        if stopping:
            raise StartupCancelled
        process = subprocess.Popen(args)
        processes.append(process)
        LOGGER.info("event=process_started service=%s pid=%s", name, process.pid)
        return process

    def ready(check: Callable[[], bool]) -> None:
        wait_ready(check, processes, cancelled=lambda: stopping)

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    READY.unlink(missing_ok=True)
    try:
        rom = Path("/rom/pokered.gbc")
        if not rom.is_file() or rom.stat().st_size < 0x150:
            raise RuntimeError("ROM missing or invalid; run the documented source build")
        model = os.environ.get("SAMEBOY_MODEL", "cgb-e")
        if model not in {"cgb-e", "dmg"}:
            raise RuntimeError("SAMEBOY_MODEL must be cgb-e or dmg")
        link = Path("/profile/game.gb")
        if link.is_symlink():
            link.unlink()
        elif link.exists():
            raise RuntimeError("/profile/game.gb exists and is not the managed ROM symlink")
        link.symlink_to(rom)
        # Without a window manager SDL's fullscreen request doesn't resize its
        # initial 2x window. Match the virtual screen to that native window.
        start("display", "Xvfb", ":99", "-screen", "0", "320x288x24", "-nolisten", "tcp")
        ready(lambda: command_ready("xdpyinfo"))
        start(
            "pulse",
            "pulseaudio",
            "--daemonize=no",
            "--exit-idle-time=-1",
            "--log-target=stderr",
            "--high-priority=no",
            "--realtime=no",
            "-n",
            "--file=/app/pulse.pa",
            "--disallow-exit",
        )
        ready(lambda: command_ready("pactl", "set-default-sink", "game"))
        audio_ready = Path("/tmp/sameboy-audio-ready")
        audio_ready.unlink(missing_ok=True)
        start("audio", "python3", "/app/audio.py")
        ready(audio_ready.is_file)
        emulator = start("sameboy", "/opt/sameboy/sameboy", "--model", model, str(link))
        start(
            "vnc",
            "x11vnc",
            "-display",
            ":99",
            "-localhost",
            "-rfbport",
            "5900",
            "-forever",
            "-shared",
            "-nopw",
            "-quiet",
            "-noxdamage",
        )
        ready(lambda: tcp_ready(5900))
        start("websockify", "websockify", "127.0.0.1:6080", "127.0.0.1:5900")
        ready(lambda: tcp_ready(6080))
        start("nginx", "nginx", "-c", "/app/nginx.conf", "-g", "daemon off;")
        ready(lambda: tcp_ready(8081))
        READY.write_text(json.dumps([process.pid for process in processes]))
        LOGGER.info("event=runtime_ready model=%s profile=/profile", model)
        while not stopping:
            for process in processes:
                if process.poll() is not None:
                    raise RuntimeError(
                        f"required process exited pid={process.pid} code={process.returncode}"
                    )
            time.sleep(0.2)
    except StartupCancelled:
        LOGGER.info("event=startup_cancelled outcome=stopping")
    except Exception:
        LOGGER.exception("event=runtime_failure")
        result = 1
    finally:
        READY.unlink(missing_ok=True)
        if emulator is not None and emulator.poll() is None and not stop_emulator(emulator):
            result = 1
        for process in reversed(processes):
            stop_process(process)
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)sZ %(levelname)s %(message)s")
    sys.exit((0 if health() else 1) if "--health" in sys.argv else main())
