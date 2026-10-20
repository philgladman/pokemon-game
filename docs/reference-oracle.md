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

The tool then starts PyBoy 2.8.1 with its null window, drives a clean cartridge
through the normal new-game flow using pinned debug symbols, and waits for the
first settled Red's House 2F overworld state. It compares that checkpoint with a
new Python `GameSession`; a map, position, facing, actor, flag, starter, or party
mismatch fails the command. Matching source and runtime traces are written under
`.cache/oracle/traces/`. All waits are frame-bounded and report the last
normalized map, player, facing, and script state on failure. Frames are retained
for diagnostics but are not treated as equivalent wall-clock timing.

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
