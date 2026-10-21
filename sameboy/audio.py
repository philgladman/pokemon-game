"""Stream the container's private PulseAudio monitor as bounded, live PCM."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

LOGGER = logging.getLogger("sameboy.audio")
FRAME_BYTES = 3840  # 20 ms, 48 kHz, signed little-endian 16-bit stereo.
MAX_CLIENTS = 8
READY = Path("/tmp/sameboy-audio-ready")


class AudioBridge:
    def __init__(self) -> None:
        self.clients: set[ServerConnection] = set()

    async def connect(self, socket: ServerConnection) -> None:
        if len(self.clients) >= MAX_CLIENTS:
            await socket.close(code=1013, reason="audio client limit")
            return
        self.clients.add(socket)
        try:
            await socket.wait_closed()
        finally:
            self.clients.discard(socket)

    async def send(self, socket: ServerConnection, pcm: bytes) -> None:
        try:
            # A slow tab must never create an unbounded audio backlog.
            await asyncio.wait_for(socket.send(pcm), timeout=0.1)
        except (TimeoutError, ConnectionClosed):
            self.clients.discard(socket)
            await socket.close(code=1013, reason="audio consumer too slow")

    async def broadcast(self, pcm: bytes) -> None:
        await asyncio.gather(*(self.send(socket, pcm) for socket in tuple(self.clients)))


async def main() -> None:
    bridge = AudioBridge()
    capture = await asyncio.create_subprocess_exec(
        "parec",
        "--device=game.monitor",
        "--format=s16le",
        "--rate=48000",
        "--channels=2",
        "--latency-msec=20",
        stdout=asyncio.subprocess.PIPE,
    )
    try:
        async with serve(
            bridge.connect,
            "127.0.0.1",
            8765,
            max_size=1024,
            max_queue=1,
            write_limit=8192,
            close_timeout=0.2,
            ping_interval=20,
        ):
            READY.touch()
            LOGGER.info("event=audio_ready format=s16le rate=48000 channels=2")
            assert capture.stdout is not None
            while True:
                pcm = await capture.stdout.readexactly(FRAME_BYTES)
                await bridge.broadcast(pcm)
    finally:
        READY.unlink(missing_ok=True)
        if capture.returncode is None:
            capture.terminate()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(capture.wait(), 2)
            if capture.returncode is None:
                capture.kill()
                await capture.wait()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)sZ %(levelname)s %(message)s")
    asyncio.run(main())
