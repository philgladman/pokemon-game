# Pokémon — original game in a browser

Play source-built Pokémon Red in SameBoy through Docker and a Mac browser.
The original ROM provides game behavior and graphics; future customizations
will change the game source. See [project phases](PHASES.md).

## Quickstart

Prerequisites: Git, Docker Desktop running, and Docker Compose v2. No host
Python, Node.js, RGBDS, compiler, or native emulator installation is needed.
From a fresh clone of this repository:

```bash
cd pokemon-game
git clone https://github.com/pret/pokered.git external/pokered
git -C external/pokered checkout af519899719f0754965776faac0e836a3b906e6d
docker compose -p pokemon-baseline -f compose.sameboy.yml run --build --rm rom-builder
docker compose -p pokemon-baseline -f compose.sameboy.yml up --build -d --wait
```

Open <http://127.0.0.1:8081> and click the display to focus it. Initial builds
download pinned tools and compile locally, so they take longer than later starts.
The builder checks the clean pinned source, builds in temporary storage, and
verifies the canonical ROM before publishing it to ignored `.cache/` storage.
No ROM, Pokémon source, or proprietary media is committed here.

## Controls and saves

Arrows move; X is A, Z is B, Enter is Start, Backspace is Select, Escape opens
SameBoy's menu, and Space holds turbo. Audio is off until **Enable audio** is
clicked. Use the game's Start → SAVE to save progress.

```bash
# Start again after stopping/removing containers; reuse the saved profile.
docker compose -p pokemon-baseline -f compose.sameboy.yml up -d --wait
# Stop and remove containers, retaining the profile.
docker compose -p pokemon-baseline -f compose.sameboy.yml down
```

Keep the same `-p pokemon-baseline` project name to reuse
`pokemon-baseline_profile`. **Do not use `down -v`: it deletes saves.** Stop
SameBoy before rebuilding its mounted ROM, then start it again. The builder is
an explicit one-shot service, not part of ordinary startup.

## Documentation

- [SameBoy workflow](docs/sameboy.md): building, controls, profiles, audio,
  custom ROM input, and troubleshooting.
- [Project phases](PHASES.md) and [changelog](CHANGELOG.md).

## Development

Contributors need Python 3.12+ and Node.js 22+ in addition to Docker. Browser
modules use native JavaScript; there is no package installation or bundling step.

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
make check
```

Checks cover Python formatting, linting, types, runtime supervision, ROM
publication, browser controls, and audio buffering. Gameplay itself runs in
SameBoy; Python manages the container processes and audio transport.
