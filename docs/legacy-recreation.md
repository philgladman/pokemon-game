# Legacy Python/browser recreation

This preserved experiment is no longer the active game architecture. For the
original game in SameBoy, use the [current quickstart](../README.md).
Run commands below from the repository root.

A Python/browser compatibility runtime that interprets the Pallet Town portion
of [`pret/pokered`](https://github.com/pret/pokered). The Python engine owns
movement, collision, interaction, dialog state, and warps. The default browser
client renders the same normalized state as a 160×144 retro Canvas view.

See [project phases](../PHASES.md) for the direction change and milestone history.

The original 2D game can also run in SameBoy through Docker and noVNC at
<http://127.0.0.1:8081>, with persistent profiles and opt-in browser audio.
See the separate [SameBoy workflow](sameboy.md) for source compilation,
startup, controls and saves. The recreation below remains on port 8080.

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

New sessions use the canonical `NewGameWarp` and begin in Red's House 2F at
`(3,6)`. Set `POKEMON_PLAYER_NAME`
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

Controls: WASD or arrow keys move; E or Space interacts, advances text, and
confirms a choice. In a choice, Up/W and Down/S change the selection, while
Escape or Backspace selects the source-compatible No/cancel result.
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
        │ immutable world + focused story/species definitions
        ▼
Python-authoritative GameSession + session-local StoryRunner
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

Direct `text_far` interactions work. The focused Pallet story adapter compiles
the conditional Mom/TV/Oak/lab/starter scripts needed by Phase 3A into a typed,
provenance-bearing trigger/condition/command graph and rejects source drift
outside that supported shape; unrelated conditional assembly is still reported
as unsupported. Source text compatibility resolves tokens such
as `#MON`, `<PLAYER>`, `<RIVAL>`, and the starter name buffer at execution time.
Python owns event flags, choices, actor visibility and position, the minimal
party, and the first rival battle. After the source challenge and approach, a
shared battle overlay works with both world renderers. Choose starting moves
with arrows/WASD and E/Space, or click a move; Enter activates a focused button.
Text advances explicitly before the next turn becomes available.

Phase 3B's battle engine is available independently of the browser:
`PokeredSource.build_battle()` parses the three level-5 starters, starting moves,
trainer DVs, rival party mapping, and stat modifier table. The immutable Pokémon
factory preserves player DVs at realization; `create_rival_battle()` accepts that
existing Pokémon, and `resolve_turn()` returns a new state plus ordered events.
The caller injects random bytes, making source-specific critical hits, accuracy,
damage rejection draws, rival move selection, debuffs, PP, Struggle/recoil, and
fainting reproducible. This models battle decision calls, not the Game Boy's
frame-dependent PRNG. Unsupported species, levels, moves, and commands fail
explicitly. The player is realized once when granted and retains those DVs,
stats, HP, and PP throughout combat. Python sends the ordered text and HP/PP
frames; battle/turn tokens and acknowledged presentation batches prevent replay
or double submissions. Source front/back starter PNGs and move names are loaded
from the pinned checkout. Artwork failures can be retried without advancing a
turn. Winning awards source experience and stat experience, raises the starter
to level 6, and adds ¥175 to the initial ¥3000 wallet. Frame-specific level,
maximum HP, and stats preserve the source presentation order. Losing in the lab
keeps experience and money unchanged. After the final battle batch is
acknowledged, both outcomes heal the party before the rival's farewell, animate
his departure, and return control in the lab. Oak uses his postbattle text and
the rival cannot challenge again. The overworld's party summary stays minimal.

For live ROM checks of every granted starter's observed DVs, stats, starting
moves, PP, level, and zero stat experience against the Python factory, run:

```bash
.venv/bin/python -m tools.pokered_oracle check --battle-stats
```

Optional live battle-turn and outcome comparisons use `oracle check --battle`;
see [reference oracle](reference-oracle.md) for coverage and evidence.
A full assembly VM, Route 1, saves, and the rest of Kanto remain out of scope.

Each displayed choice and story-authored map transition has a unique session
token. The server rejects stale tokens and replays duplicate request IDs without
applying an action twice. Story transitions resume only after the renderer has
completed the shared fade and acknowledged the visibly applied destination.
If destination rendering fails, the transition remains gated and uncommitted so
E or Space can retry the same state without advancing the story behind the
failed view.

Scripted story movement is sent as typed multi-actor tracks. The active renderer
animates every track and acknowledges the cue only after successful completion;
the server then commits the positions and advances the story. Stale, duplicate,
or unknown acknowledgements cannot mutate session state.

Source PNGs are available only through the allowlisted
`/source-assets/{tilesets|sprites|pokemon-front|pokemon-back}/...` endpoint.
The two Pokémon categories expose only the six starter front/back files.
Arbitrary files from the
checkout cannot be requested.

## Verification

```bash
make check
```

This runs Ruff, strict mypy, pytest, a live source parse, TypeScript checks,
Vitest, and the production frontend build. Run only the canonical-source check
with `make source-check`.

An optional [headless reference oracle](reference-oracle.md) builds the
canonical Red ROM and debug symbols in the ignored cache with RGBDS 1.0.4, then
compares the clean-ROM new-game state and all Phase 3A Pallet story branches
against the Python runtime with PyBoy 2.8.1. Coverage includes movement timing,
house transitions, signs/NPCs, both Oak intercept columns, lab positioning, and
all starter/counter-starter choices. It is intentionally excluded from `make
check`; run it explicitly with `make oracle-check`.
