# Pokémon — original Gen 1 and Gen 2 games in a browser

Play source-built Red, Blue, Yellow, Gold, Silver, or Crystal in SameBoy through
Docker and a Mac browser. The original ROM provides game behavior and graphics;
future customizations will change the game source. See [project phases](PHASES.md).

## Quickstart

Prerequisites: Git, Docker Desktop running, and Docker Compose v2. No host Python,
Node.js, RGBDS, compiler, native emulator, or manual game-source clone is needed.
Clone this repository, enter its directory, then run:

```bash
docker compose up --build -d --wait
```

Open <http://127.0.0.1:8080> and click the display to focus it. Red is the default.
Choose another game with the same command:

```bash
POKEMON_GAME=crystal docker compose up --build -d --wait
```

Supported selectors: `red`, `blue`, `yellow`, `gold`, `silver`, `crystal`.
Use the same selector for subsequent startup commands, or put
`POKEMON_GAME=crystal` in an ignored `.env` file. Initial builds fetch source and
compile pinned tools; later starts fetch updates but reuse verified ROMs. The
builder never follows a moving branch or builds in your host source checkout.
Network access is required for source preparation, including cached starts.
No ROM, Pokémon source, or proprietary media is committed here.

## Controls and saves

Arrows move; X is A, Z is B, Enter is Start, Backspace is Select, Escape opens
SameBoy's menu, and Space holds turbo. Audio is off until **Enable audio** is
clicked. Use the game's Start → SAVE to save progress.

```bash
# Stop/remove containers without deleting games or saves.
docker compose down
# Start Red again, using its existing save.
docker compose up -d --wait
```

The default project name remains `pokemon-baseline`, retaining the existing
`pokemon-baseline_profile` save volume. Red keeps `/profile/game.sav`; other
games use separate `/profile/games/<game>/` profiles, including preferences,
states, and RTC data. Switching games does not overwrite Red's progress.
**Do not use `down -v`: it deletes saves and cached source/ROM volumes.**

## Documentation

- [SameBoy workflow](docs/sameboy.md): pinned game catalog, source overrides,
  profiles, custom ROMs, audio, image builds, and troubleshooting.
- [Project phases](PHASES.md) and [changelog](CHANGELOG.md).

## Development

Contributors need Python 3.12+ and Node.js 22+ in addition to Docker. Browser
modules use native JavaScript; there is no package installation or bundling step.

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
make check
```

Checks cover Python formatting, linting, types, source preparation, ROM
publication, runtime supervision, browser controls, and audio buffering.
Gameplay runs in SameBoy; Python manages builds, processes, and audio transport.
