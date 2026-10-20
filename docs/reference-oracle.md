# Pokémon Red reference oracle

The reference oracle is an optional developer tool for checking runtime
assumptions against the pinned `pret/pokered` revision in a headless emulator.
It is deliberately separate from the normal test suite: the application does
not depend on an emulator, RGBDS, or a ROM at runtime.

## Prerequisites

- The pinned source checkout described in the [README](../README.md#source-setup).
- RGBDS **1.0.4**, with `rgbasm`, `rgblink`, `rgbfix`, and `rgbgfx` on `PATH`.
  Alternatively, set `RGBDS` to the tool-name prefix used by the upstream
  Makefile, such as `/opt/rgbds-1.0.4/bin/`.
- The exact optional emulator dependency:

  ```bash
  .venv/bin/pip install -e '.[oracle]'
  ```

## Run

Inspect the source and exact local tool versions without building or writing
anything:

```bash
.venv/bin/python -m tools.pokered_oracle doctor
```

`doctor` exits zero when the pinned source, RGBDS 1.0.4, and PyBoy 2.8.1 are
ready. It reports a valid, missing, or invalid cache separately because
`build`/`check` can create or replace that ignored cache. A source or tool
failure exits 2 with an actionable message.

```bash
make oracle-check
```

The command validates the pinned, clean source; exports tracked source files to
`.cache/oracle/build/pokered`; runs `make DEBUG=1 red` there; and verifies the
canonical Red ROM SHA-1
`ea9bcae617fdf159b045185467ae58b2e4a48b9a`. `DEBUG=1` asks RGBDS to emit the
symbol file; it does not enable a modified debug ROM.

The tool then starts PyBoy 2.8.1 with its null window and drives a clean
cartridge through the normal new-game flow using pinned debug symbols. After
the initial Red's House 2F comparison, the same semantic gameplay-driver
contract exercises both PyBoy and a new Python `GameSession` through:

- changed-direction taps, held-input resampling, continuous movement, and
  same-facing fresh presses;
- Red's House stairs, exit columns 2 and 3 with reentry after each, Mom, and the TV;
- all four Pallet signs plus the live wandering girl and fisher;
- both source Oak-intercept columns and the complete escort/lab-entry sequence;
- Charmander, Squirtle, and Bulbasaur No/Yes choices, party grants, and each
  rival counter-selection, stopping before the battle boundary.

Named contracts compare only stable gameplay state relevant to each checkpoint:
map/player state, interaction identity and lifecycle, selected actor
position/visibility/facing, event flags, starter semantics, and party species
and level. Wandering NPC idle coordinates, incidental sprite facings, script
scratch bytes, and absolute emulator frame numbers are not treated as gameplay
equivalence. Movement timing is checked separately against the source cadence:
roughly two Game Boy frames to resample a held changed direction and sixteen
frames per tile, each with a one-frame tolerance.

The timing check reads the browser's movement duration and held-turn resample
constants and converts them to Game Boy frames. A fresh changed-direction runtime
input must return a turn without moving before continued input is sent.

Oak approach, column correction, escort, and lab entry also compare complete
ordered tile paths for each scripted actor and the player, including visibility
changes. Source paths are observed frame by frame. The synchronized outdoor Oak
engine leaves NPC map coordinates unchanged, so its path comes from completed
live movement-buffer entries and index advances. Runtime paths expand the actual
movement cues before acknowledging them. Matching endpoints alone cannot pass.

During source warps, the destination map ID precedes coordinate installation.
Only an observed `WarpFound2` call plus a matching source door and destination
allows that door coordinate to be attributed to the departing map. The runtime
performs ordinary door warps atomically: its intermediate exterior arrival and
automatic step are a projection of the existing warp metadata/policy, compared
against source observations, rather than separately observed runtime states.
Choice-open checkpoints compare menu options, cursor, unselected starter/party
state, and ball visibility before both No and Yes. Explicitly selected absent
values are compared as well as present values.

PyBoy save states and deep-copied runtime sessions provide in-memory checkpoints
at new game, Pallet exploration, and the lab choice. Matching source/runtime
traces are written under `.cache/oracle/traces/`, including fresh partial coverage
traces on failure. All waits are frame-bounded and
report normalized map, player, facing, and script state on failure. A mismatch
or timeout exits nonzero and names the failing contract.

To build and validate the local artifacts without launching PyBoy:

```bash
.venv/bin/python -m tools.pokered_oracle build
```

Pass `--force-build` to either command to replace the ignored cached build.
Use `--source-root /path/to/pokered` when the checkout is not at
`external/pokered`.

## Artifact policy

The source checkout is never built in place. The ROM, symbols, save states, and
traces stay under ignored `.cache/oracle`; save-state checkpoints are in memory
only. The command rejects adjacent `.ram` or `.rtc` cartridge sidecars before
starting PyBoy, so a prior emulator run cannot silently change the new-game
path. Do not copy generated ROMs, saves, screenshots, or traces into tracked
directories. This project contains no ROM or proprietary media.
