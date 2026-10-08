# Pallet Town 3D

A personal-use Phase 1 vertical slice inspired by the grid-based structure of
Pokémon Red/Blue. It renders a source-derived Pallet Town layout in Three.js,
while Python owns movement, collision, interaction, dialog, and map transitions.

This repository contains no ROM, ripped graphics, audio, or proprietary game
assets. Phase 1 uses original geometric placeholders. The ignored
`external/pokered/` checkout is an optional source reference and is never
vendored.

## Run with Docker

Requirements: Docker with Compose support.

```bash
docker compose up --build
```

Open <http://localhost:8080>. Stop with `Ctrl+C` and remove the containers with
`docker compose down`.

Controls:

- Move: `WASD` or arrow keys
- Interact / advance dialog: `E` or `Space`
- Enter the player's house through the left-hand northern doorway; walk back
  through the interior's lower doorway to exit.

The browser connects only to port 8080. Nginx serves the built frontend under
`/frontend/`, proxies `/api` and `/ws` to the private backend service, and
reserves `/assets/` for backend-served gameplay assets.

## Local development

Requirements: Python 3.12+, Node.js 22+, and npm.

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
cd frontend
npm ci
cd ..
```

Run the backend in one terminal:

```bash
make backend-dev
```

Run Vite in another:

```bash
make frontend-dev
```

Open <http://localhost:5173>. Vite proxies API, WebSocket, and `/assets`
traffic to the backend at <http://localhost:8000>.

## Tests and checks

Run the complete backend, data, and frontend suite:

```bash
make check
```

The individual commands are:

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy
.venv/bin/pytest
.venv/bin/python -m tools.compile_data --check
cd frontend && npm run typecheck && npm test && npm run build
```

## Architecture

```text
Browser (Three.js + TypeScript)
        │ movement/interaction intents
        ▼
FastAPI WebSocket (/ws/game)
        │ one isolated GameSession per connection
        ▼
Python grid engine
        │ validated runtime world
        ▼
generated JSON ← compiler ← imported YAML + world overlay + asset manifest
```

The browser never predicts collision or changes logical player coordinates. It
interpolates only positions confirmed by the server. A `GameSession` owns one
connection's map, position, facing direction, dialog cursor, and monotonically
increasing state version. Moving onto a doorway atomically changes map and
arrival position.

Useful endpoints:

- `GET /api/health`
- `GET /api/version`
- `WS /ws/game`

Client messages are discriminated by `type`, carry a `request_id`, and are
validated before reaching the engine. Server state messages echo that ID and
include `state_version`.

## Game data pipeline

There are four deliberate layers:

1. `data/yaml/imported/pallet_town.yaml` is deterministic source-derived data:
   block IDs, logical collision tile IDs, surfaces, warps, and object positions.
2. `data/yaml/world.yaml` is the human-authored gameplay overlay: display names,
   appearance IDs, original Phase 1 dialog, enabled NPCs, spawn, and the one
   supported building connection.
3. `data/yaml/assets.yaml` maps those appearance IDs to renderer-owned primitive
   or GLB definitions. GLB entries include a primitive fallback, so changing an
   NPC or tree model does not require Python engine or gameplay-schema changes.
4. `data/generated/json/world.json` is strict, validated runtime data loaded by
   FastAPI.

Warp destinations are not authored twice. Imported map constants and one-based
source warp indices determine the destination map and position. The overlay
only supplies facing and the previous-map context required by source
`LAST_MAP` warps.

The importer currently supports only the Pallet Town Phase 1 bundle (Pallet
Town plus the connected first-floor interior). Unknown source syntax fails with
an error; `--all` intentionally remains unsupported.

To reproduce the import from the pinned canonical reference:

```bash
git clone https://github.com/pret/pokered.git external/pokered
git -C external/pokered checkout af519899719f0754965776faac0e836a3b906e6d
.venv/bin/python -m tools.pokered_importer --map pallet_town
.venv/bin/python -m tools.pokered_importer --map pallet_town --check
```

Compile edited YAML into runtime JSON:

```bash
.venv/bin/python -m tools.compile_data
.venv/bin/python -m tools.compile_data --check
```

All YAML is loaded safely with duplicate-key rejection and validated without
string-to-number or string-to-boolean coercion. The compiler also checks map
dimensions, tile and appearance references, collisions, positions, duplicate
occupancy, source-derived warp destinations, and cross-map references. Visual
overrides cannot change collision imported from the reference source.

To replace a placeholder later, change only its entry in
`data/yaml/assets.yaml`, for example from `type: primitive` to `type: gltf` with
an `/assets/...glb` URL, scale, and primitive fallback. Put the referenced file
under the repository's root `assets/` tree—for example,
`/assets/models/tree.glb` resolves to `assets/models/tree.glb`. That directory
is the single asset source: FastAPI serves it, while both Vite development and
production Nginx proxy the same `/assets` URL. Assets are neither copied into
the frontend source tree nor duplicated between environments. Vite writes
compiled JavaScript and CSS under the separate `/frontend/` namespace, which
Nginx serves locally, so those bundles cannot collide with gameplay assets.
Three.js loads GLB support on demand and retains the declared primitive if
loading fails.

## Phase 1 scope

Included: Pallet Town exterior, one connected interior, source-derived grid
collision, two town NPCs, an interior NPC, server-owned dialog, typed transport,
primitive 3D rendering, and Docker Compose.

Not included: battles, Pokémon data, catching, starters, Oak's story sequence,
Route 1, inventory, save/load, or polished assets.
