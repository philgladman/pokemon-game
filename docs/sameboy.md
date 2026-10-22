# Original game in a browser

The current workflow runs SameBoy's Linux SDL frontend on a private virtual
display in Docker Desktop, with noVNC video and a separate browser audio stream.
SameBoy uses Mesa software OpenGL on a 320×288 virtual display (2× Game Boy
resolution), scaled to fit the browser. Matching the window and virtual display
avoids SDL fullscreen cropping without requiring a desktop window manager.
Keep SameBoy's window scale at its default 2×; use browser zoom to resize the
player. A larger emulator window would exceed this fixed virtual display.

## Build and play

Only Git, Docker Desktop, and Compose v2 are required on the host. From the
repository root, fetch the canonical source and build the local Red ROM:

```bash
git clone https://github.com/pret/pokered.git external/pokered
git -C external/pokered checkout af519899719f0754965776faac0e836a3b906e6d
docker compose -p pokemon-baseline -f compose.sameboy.yml run --build --rm rom-builder
docker compose -p pokemon-baseline -f compose.sameboy.yml up --build -d --wait
```

The `rom-builder` service is profile-gated and runs only when explicitly
requested. It has RGBDS 1.0.4, Python, Git, and compiler tools inside its Docker
image. Source is mounted read-only. The builder rejects a different HEAD or
normal tracked staged/unstaged edits, ignores untracked files, and exports the pinned Git tree
to temporary storage rather than building the checkout. Even files hidden by
Git index flags cannot enter the build. A verified canonical Red SHA-1
`ea9bcae617fdf159b045185467ae58b2e4a48b9a` is required before publishing
`pokered.gbc` and `pokered.sym` under `.cache/roms/pokered`.
Concurrent builder invocations serialize; compile or hash failures leave the
previous artifacts intact; unrelated files in the output directory are retained.

For subsequent rebuilds, **stop SameBoy before replacing its mounted ROM**:

```bash
docker compose -p pokemon-baseline -f compose.sameboy.yml stop sameboy
docker compose -p pokemon-baseline -f compose.sameboy.yml run --build --rm rom-builder
docker compose -p pokemon-baseline -f compose.sameboy.yml up -d --force-recreate --wait
```

This builder intentionally supports only canonical Red, not patched games.
Source customization and Red/Blue/Yellow/Gold/Silver/Crystal game selection
remain future work. A separately compiled custom ROM can already be supplied
with `SAMEBOY_ROM` as shown below.

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
another `SAMEBOY_PORT`.

The workflow does not change or complete the future custom-ROM and iPhone
milestones in [the roadmap](../PHASES.md).
