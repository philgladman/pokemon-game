# Original game in a browser

This separate workflow runs SameBoy's Linux SDL frontend on a private virtual
display in Docker Desktop, with noVNC video and a separate browser audio stream.
It preserves the Python recreation and its `docker-compose.yml` on port 8080.
SameBoy uses Mesa software OpenGL on a 320×288 virtual display (2× Game Boy
resolution), scaled to fit the browser. Matching the window and virtual display
avoids SDL fullscreen cropping without requiring a desktop window manager.
Keep SameBoy's window scale at its default 2×; use browser zoom to resize the
player. A larger emulator window would exceed this fixed virtual display.

## Build and play

Complete the [source setup](../README.md#source-setup) and install the optional
[oracle build prerequisites](reference-oracle.md). Compile and verify the local
canonical Red ROM:

```bash
.venv/bin/python -m tools.pokered_oracle build
docker compose -p pokemon-baseline -f compose.sameboy.yml up --build -d --wait
```

Open <http://127.0.0.1:8081>. Click the display to focus it. Arrows move, X is A,
Z is B, Enter is Start, Backspace is Select, Escape opens SameBoy's menu, and
Space holds turbo. Click **Enable audio** to allow the browser to play sound.
Use **Reconnect** after restarting the container. Audio requires a browser with
AudioWorklet support; localhost is a secure browser context. No native Mac
emulator, host display, audio socket, Nintendo BIOS, or downloaded ROM is used.

The default CGB-E model uses SameBoy's open-source boot ROM and the cartridge's
native compatibility palette. For monochrome, set `SAMEBOY_MODEL=dmg` before
`up --force-recreate`. This changes hardware emulation, not game content.

## Saves and isolated profiles

Use the game's normal Start → SAVE flow. Battery RAM is stored in
`/profile/game.sav`, independently of the container and read-only ROM. SameBoy
also stores preferences and any manually created emulator states in the same
profile volume. The managed `/profile/game.gb` symlink gives SameBoy a stable
writable location for its filename-derived save files.

Keep the same Compose project name to reuse a profile:

```bash
docker compose -p pokemon-baseline -f compose.sameboy.yml restart
docker compose -p pokemon-baseline -f compose.sameboy.yml up -d --force-recreate --wait
docker compose -p pokemon-baseline -f compose.sameboy.yml down
```

`down` retains saves. **Do not add `-v` unless you intend to delete that project's
profile.** Normal stop requests SDL quit and waits for SameBoy to flush battery
RAM before shutting down its display and audio. Forced termination, Docker
Desktop crashes, or power loss cannot guarantee a final save flush.

Use a different project and port for a modified ROM:

```bash
SAMEBOY_PORT=8082 SAMEBOY_ROM=/absolute/path/to/local/modified.gbc \
  docker compose -p pokemon-modified -f compose.sameboy.yml up --build -d --wait
```

This creates `pokemon-modified_profile`, separate from
`pokemon-baseline_profile`. Reusing a project with another ROM intentionally
reuses its save; choose the project name carefully. ROM paths must already
exist; Compose refuses a missing bind source. Keep compiled ROMs, exported
saves and emulator artifacts in ignored `.cache/` storage.

## Audio and runtime behavior

PulseAudio captures only the container's private null sink. A loopback WebSocket
bridge sends 48 kHz, stereo signed 16-bit PCM to an AudioWorklet. The browser
resamples for its actual output rate, bounds queued audio, drops stale samples
and emits silence on underrun. This is an uncompressed local stream, roughly
192 KB/s per listening browser, with up to eight audio clients. Disable and
enable audio again after an audio failure. Visual noVNC connectivity alone does
not establish audio delivery. Automated checks verified nonzero PCM, nonzero
browser worklet output, bounded buffering and reconnect with browser output
muted. Actual listening quality remains a separate manual acceptance check.

Only port 8081 is published, bound to the Mac's loopback interface. VNC,
websockify and PCM sockets stay inside the container. This is a local desktop
workflow, without authentication; do not expose it through a proxy or public
interface. The container runs as UID 1000 without added capabilities or host
device access. SameBoy, noVNC, and RGBDS source archives have pinned versions and
verified SHA-256 checksums in the Dockerfile. OS packages receive Debian updates
when rebuilding.

## Troubleshooting

```bash
docker compose -p pokemon-baseline -f compose.sameboy.yml ps
docker compose -p pokemon-baseline -f compose.sameboy.yml logs --tail=80
```

Startup and health checks are bounded; a failed display, audio, emulator or
transport stops the container. `runtime_ready` means all transports started.
`emulator_stopped outcome=graceful` confirms the SDL quit path completed. A
`save_flush=unconfirmed` error means the emulator had to be forced down; inspect
the logs before relying on the most recent save. If 8081 is occupied, choose
another `SAMEBOY_PORT`. Leave the original recreation services on 8080 alone.

The workflow does not change or complete the future custom-ROM and iPhone
milestones in [the roadmap](../PHASES.md).
