# Pokémon Red browser runtime

A Python/browser compatibility runtime that interprets the Pallet Town portion
of [`pret/pokered`](https://github.com/pret/pokered). The Python engine owns
movement, collision, interaction, dialog state, and warps. The default browser
client renders the same normalized state as a 160×144 retro Canvas view.

No Pokémon graphics or source-derived game data are committed here. They are
read at runtime from a local, ignored `pret/pokered` checkout.

## Source setup

The runtime intentionally validates the pinned revision
`af519899719f0754965776faac0e836a3b906e6d`:

```bash
git clone https://github.com/pret/pokered.git external/pokered
git -C external/pokered checkout af519899719f0754965776faac0e836a3b906e6d
```

The default source root is `external/pokered`. Set `POKERED_SOURCE_ROOT` to use
another checkout. Missing or unsupported source fails startup explicitly; the
game does not fall back to handwritten Pokémon content. Startup also validates
the checkout's canonical Git index against the pinned tree and hashes every
tracked worktree file, so modified, deleted, or staged tracked source fails
before parsing. Untracked local files are intentionally ignored.

The demo intentionally starts at Pallet Town's source fly-warp position `(5,6)`
so the whole vertical slice is immediately explorable. The canonical new-game
script instead begins in Red's House 2F at `(3,6)`. Set `POKEMON_PLAYER_NAME`
and `POKEMON_RIVAL_NAME` to override the normalized seven-character `RED` and
`BLUE` defaults used for source text tokens.

## Run

With Docker and Compose:

```bash
docker compose up --build
```

Open <http://localhost:8080>. Compose mounts `external/pokered` read-only into
the backend container.

For local development, install Python 3.12+, Node.js 22+, and npm:

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
cd frontend && npm ci && cd ..
```

Then run `make backend-dev` and `make frontend-dev` in separate terminals and
open <http://localhost:5173>.

Controls: WASD or arrow keys move; E or Space interacts and advances text.
After input returns to neutral, tapping a direction different from the last
facing turns without walking; holding it is resampled after about 34 ms and then
walks. Pressing the same direction walks immediately. Successful tiles use
eight 2-pixel advances over a 268 ms cadence, with the retro renderer alternating
the walking foot across continuous tiles. Map changes use a staged Game Boy-style
fade in both renderers. Building exits trigger only when moving outward from the
boundary door tile; returning outdoors includes the source's automatic step
south, so pressing Up immediately re-enters. Movement and warp decisions remain
grid-based and Python-authoritative.

The retro Canvas renderer is the default. The preserved experimental Three.js
view is loaded only when opening `?renderer=3d`.

## Architecture

```text
external/pokered (canonical, ignored)
        │ live focused parsers
        ▼
PokeredSource / GameSource protocol
        │ normalized Pydantic world built in memory
        ▼
Python-authoritative GameSession
        │ renderer-neutral logical WebSocket state
        ├── Canvas retro renderer + /api/renderers/retro/maps/{map_id}
        └── isolated Three.js renderer (?renderer=3d)
```

`PokeredSource` currently parses all five Pallet maps: Pallet Town, Red's House
1F and 2F, Blue's House, and Oak's Lab. It reads map dimensions, block layouts,
blocksets, tilesets, collision IDs, objects, background events, warps,
connections, initial visibility, sprites, and directly referenced text while
retaining source file/symbol/revision provenance.

The WebSocket snapshot contains logical map walkability and sprite identifiers,
not renderer URLs, tile graphics, or a 3D asset manifest. The retro adapter
requests its tileset, expanded tile map, and allowlisted sprite resources only
when a map changes. The Three.js adapter consumes that same logical snapshot and
separately caches its source-derived map projection and project-owned appearance
manifest from `data/config/three_d.json`. It preserves the Phase 1 GLB/primitive
fallback, shadow, and movement-interpolation pipeline. Project-owned GLBs belong
under `assets/` and use `/assets/...` manifest URLs in local development and
Docker.

Move intents include whether they continue the current held-input sequence.
`GameSession` owns the last-stop direction and one-shot turn check, so browser
timing never decides whether a logical step or turn is legal.

Direct `text_far` interactions work. Conditional `text_asm` scripts are exposed
as unsupported instead of being guessed. Source text compatibility resolves
tokens such as `#MON`, `<PLAYER>`, and `<RIVAL>` when dialog executes while
keeping parsed templates unchanged. The complete Oak/starter sequence,
script VM, battles, Route 1, NPC walking simulation, saves, and the rest of
Kanto remain out of scope for this milestone.

Source PNGs are available only through the allowlisted
`/source-assets/{tilesets|sprites}/...` endpoint. Arbitrary files from the
checkout cannot be requested.

## Verification

```bash
make check
```

This runs Ruff, strict mypy, pytest, a live source parse, TypeScript checks,
Vitest, and the production frontend build. Run only the canonical-source check
with `make source-check`.
