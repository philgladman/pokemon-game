# Original games in a browser

SameBoy's Linux SDL frontend runs on a private Docker virtual display, with
noVNC video and a separate browser audio stream. Mesa software OpenGL renders
at 320×288 (2× Game Boy resolution). Keep SameBoy's window scale at its default
2×; use browser zoom to resize without exceeding the fixed virtual display.

## Build and play

After cloning this project, only Docker Desktop and Compose v2 are needed:

```bash
docker compose up --build -d --wait
# Or choose blue, yellow, gold, silver, or crystal:
POKEMON_GAME=yellow docker compose up --build -d --wait
```

Open <http://127.0.0.1:8080>. Click the display to focus it. Arrows move, X is A,
Z is B, Enter is Start, Backspace is Select, Escape opens SameBoy's menu, and
Space holds turbo. Click **Enable audio** to allow sound; **Reconnect** reconnects
after a container restart. AudioWorklet support and a secure context are needed;
localhost qualifies. No native emulator, host display/audio device, Nintendo
BIOS, or downloaded ROM is used.

The default CGB-E model uses SameBoy's open-source boot ROM and cartridge-native
compatibility palette. `SAMEBOY_MODEL=dmg` selects monochrome hardware for Gen 1;
Crystal requires Game Boy Color hardware. Model selection does not alter ROMs.

## Source selection and verification

`compose.yaml` passes these same variables to the builder and player:

| Variable | Default | Purpose |
| --- | --- | --- |
| `POKEMON_GAME` | `red` | Game and its build target/filename |
| `POKEMON_SOURCE_REPO` | Selected game's catalog URL | Credential-free HTTPS Git repository |
| `POKEMON_SOURCE_VERSION` | Selected game's catalog commit | Exact lowercase 40-character commit, not a branch |
| `POKEMON_ROM_SHA1` | Selected game's canonical checksum | Required expected output checksum |
| `SAMEBOY_PORT` | `8080` | Loopback browser port |
| `SAMEBOY_MODEL` | `cgb-e` | Emulator hardware model |

The catalog in [`sameboy/games.py`](../sameboy/games.py) pins these English games
and RGBDS 1.0.4:

| Game | Source repository | Pinned commit | ROM SHA-1 |
| --- | --- | --- | --- |
| Red | [pret/pokered](https://github.com/pret/pokered) | `af519899719f0754965776faac0e836a3b906e6d` | `ea9bcae617fdf159b045185467ae58b2e4a48b9a` |
| Blue | [pret/pokered](https://github.com/pret/pokered) | `af519899719f0754965776faac0e836a3b906e6d` | `d7037c83e1ae5b39bde3c30787637ba1d4c48ce2` |
| Yellow | [pret/pokeyellow](https://github.com/pret/pokeyellow) | `b6696f24b3be84fe64cf702f5a15ba40c66b7f39` | `cc7d03262ebfaf2f06772c1a480c7d9d5f4a38e1` |
| Gold | [pret/pokegold](https://github.com/pret/pokegold) | `fc702b6d922aecce274782d68bba8639936a1182` | `d8b8a3600a465308c9953dfa04f0081c05bdcb94` |
| Silver | [pret/pokegold](https://github.com/pret/pokegold) | `fc702b6d922aecce274782d68bba8639936a1182` | `49b163f7e57702bc939d642a18f591de55d92dae` |
| Crystal (v1.0) | [pret/pokecrystal](https://github.com/pret/pokecrystal) | `5c877ef55197039c9676e8e3eec6d254b1c40fe8` | `f4cd194bdee0d04ca4eac29e09b8e4e9d818c133` |

The builder clones each repository once into a managed bare cache in the
`sources` named volume. Later runs fetch branches/tags, resolve the exact
configured commit, and export that committed tree into temporary build storage.
There is no `pull` or host checkout modification. Source locks serialize access.
An unavailable remote or revision fails startup rather than silently falling
back to stale source, even if a ROM is cached.

Builds run `make -B DEBUG=1 <game>` and require the expected ROM checksum and
nonempty symbols. Verified artifacts are atomically published together under
`/roms/<game>/<configuration digest>/` in the `roms` volume. The digest includes
repository, revision, target, filename, checksum, and toolchain. Repeat builds
verify and reuse that immutable artifact; failures cannot replace another
configuration. The runtime mounts artifacts read-only, verifies the same
selection, and starts only after the builder succeeds. A corrupt cached artifact
fails closed rather than being used.

Compatible forks/revisions can override the repository, commit, and expected
checksum together. Build targets and filenames remain those of the selected
catalog game. Arbitrary projects or toolchain requirements are not supported by
these overrides. Never disable checksum verification for a modified ROM.
Store persistent selections in ignored `.env`; otherwise repeat them for each
`up`/`run`. Do not place credentials in repository URLs.

## Images and startup

Compose's `build.context: sameboy` and `build.target` build local images, so
there is no prebuilt `image:` download for these services. The stages live in
[`sameboy/Dockerfile`](../sameboy/Dockerfile): `rom-builder` includes Git, Python,
compiler tools and RGBDS; `runtime` includes SameBoy, display, audio, and browser
transports. Debian, RGBDS, SameBoy, and noVNC inputs are pinned; source archive
SHA-256 checksums are checked. OS packages receive Debian updates on rebuild.

`rom-builder` is a one-shot startup dependency. Its successful exit is expected,
not a crashed game. `sameboy` has a health check; `--wait` waits for readiness.
An ordinary `up` runs source preparation; `restart sameboy` only restarts the
already configured emulator and does not change the selected game or fetch.

## ROM export

To build and export without launching the emulator, browser, or audio services:

```bash
POKEMON_GAME=red docker compose -f compose.export.yaml run --build --rm rom-export
```

`compose.export.yaml` extends the existing builder, sharing its pinned toolchain,
source/ROM volumes, security settings, and repository/revision/checksum variables.
It never mounts the profile volume, publishes ports, or starts the player.
With the same project name (default `pokemon-baseline`), export and gameplay
reuse verified ROMs and source caches. A different `-p` selects separate caches.
Initial exports build the selected game; cached runs still fetch source and fail
if the remote is unavailable. They are not an offline copy command.

Only the verified ROM is copied to the ignored host `.cache/exports/` folder:

| `POKEMON_GAME` | Exported file |
| --- | --- |
| `red` | `.cache/exports/pokemon-red/pokered.gbc` |
| `blue` | `.cache/exports/pokemon-blue/pokeblue.gbc` |
| `yellow` | `.cache/exports/pokemon-yellow/pokeyellow.gbc` |
| `gold` | `.cache/exports/pokemon-gold/pokegold.gbc` |
| `silver` | `.cache/exports/pokemon-silver/pokesilver.gbc` |
| `crystal` | `.cache/exports/pokemon-crystal/pokecrystal.gbc` |

Repeat exports replace the same game's file, including when source/checksum
overrides change. The copied file is checksum-verified before atomic replacement;
failures retain any previous complete export. Other exports and unrelated files
are not removed. Symbol files, saves, states, and RTC data are not exported.
Symlinked export folders/files are rejected; use an ordinary local folder.

The file can be imported into the existing SameBoy iPhone app using Files,
email, or AirDrop. No upload, email automation, or public hosting is configured.
Only use content you are authorized to use. Actual iPhone behavior and save
transfer remain separate from this Mac build/export workflow.

## Saves and migration

The top-level Compose project name defaults to `pokemon-baseline`, preserving
`pokemon-baseline_profile` without a migration command. Existing Red battery
RAM stays `/profile/game.sav`, and its old managed ROM symlink is safely replaced.
Other games have `/profile/games/<game>/game.sav`. SameBoy preferences, emulator
states, and RTC data are isolated with each game's profile too. Returning to Red
uses the same Red save. Source/ROM caches are independent of profile storage.

Use the normal Start → SAVE flow, then stop gracefully:

```bash
docker compose down
POKEMON_GAME=gold docker compose up -d --wait
```

`down` retains all volumes. **Never add `-v` unless you intend to delete saves
and caches.** Normal stop requests SDL quit and waits for battery RAM to flush.
Forced termination, Docker crashes, or power loss cannot guarantee a final flush.
Back up the profile volume before experimenting with incompatible modified ROMs.
Use a different project name (`-p pokemon-modified`) to isolate modified saves;
source and artifact caches are then also project-scoped.

## Prebuilt custom ROM

A separate overlay retains support for a locally compiled ROM without fetching
source. It deliberately bypasses the builder and canonical checksum check;
provide a ROM you trust and use a separate project/profile:

```bash
SAMEBOY_PORT=8082 SAMEBOY_ROM=/absolute/path/to/modified.gbc \
  docker compose -p pokemon-modified -f compose.yaml -f compose.custom.yaml \
  up --build -d --wait --no-deps sameboy
```

The bind source must exist; Compose will not create it. Set `POKEMON_GAME` too
if the ROM should use a non-Red per-game save slot. No ROM or save is copied into
this repository by normal startup. Use the [ROM export workflow](#rom-export)
for source-built catalog games; exporting an arbitrary prebuilt custom ROM is
not part of that command. Actual device verification remains a separate milestone.

## Audio, security, and troubleshooting

PulseAudio captures only the container's private null sink. A loopback WebSocket
streams 48 kHz stereo signed 16-bit PCM to an AudioWorklet. The browser resamples,
bounds queues, drops stale samples, and emits silence on underrun. Uncompressed
audio is roughly 192 KB/s per listening browser, capped at eight clients. Disable
and re-enable audio after a failure. Video connectivity alone does not prove
audio works. Automated checks use muted browser output; listening quality still
needs manual acceptance.

Only the browser port is published, bound to loopback. Internal VNC and PCM
sockets are not exposed. This unauthenticated workflow must not be published
through a public proxy/interface. The emulator runs as UID 1000 with no added
capabilities or host-device access. Source builds execute upstream Makefiles
inside the builder: only configure repositories you trust.

```bash
docker compose ps -a
docker compose logs --tail=80 rom-builder sameboy
```

Startup and health checks are bounded. `runtime_ready` means transports started;
`emulator_stopped outcome=graceful` confirms normal SDL quit. A
`save_flush=unconfirmed` error means forced shutdown: inspect before relying on
the latest save. If port 8080 is occupied, choose another `SAMEBOY_PORT`. Rebuild
failures do not delete saves or previously published configurations. See
[the roadmap](../PHASES.md) for custom-game and iPhone scope.
