# Project phases

A scope reference, not a dated delivery timeline. See the [setup guide](docs/sameboy.md)
for current commands and acceptance limits.

## Phase 1 — Original Pokémon Red in a Mac browser

**Status: Implemented**

- Build canonical Red from pinned source using a Docker ROM-builder service.
- Play the complete original game through SameBoy, Docker, and noVNC without a
  native Mac emulator or host compiler toolchain.
- Preserve the original game's graphics, behavior, controls, and CGB palette.
- Keep saves in a project-scoped volume independently of containers and ROM builds.
- Stream bounded audio only after a browser gesture. Transport and reconnect
  checks pass with browser output muted; listening quality needs manual acceptance.
- Verify the canonical ROM checksum, browser startup, controls, save persistence,
  graceful shutdown, and baseline/modified profile isolation.

## Phase 2 — One-command Gen 1 and Gen 2 setup

**Status: Implemented**

- Support Red, Blue, Yellow, Gold, Silver, and Crystal.
- Fetch and cache game source inside Docker; select a configured repository and
  pinned revision for reproducible builds rather than following a moving branch.
- Define each game's build target, toolchain requirements, and expected ROM checksum.
- Start the selected game with one Compose command after cloning this project.
- Keep independent saves for each game and preserve existing Red progress.
- Keep the default `pokemon-baseline` project and Red save paths unchanged.
- Verify cached artifacts on reuse and gate emulator startup on source/build success.

## Phase 3 — Source-customized games

**Status: Future**

- Modify game source and rebuild ROMs; keep the emulator responsible for execution.
- Remove trade requirements for selected evolutions and customize availability.
- Agree exact encounters and replacement evolution rules before implementing them.
- Separate baseline and modified builds, checksums, artifacts, and save profiles.

## Phase 4 — iPhone play

**Status: ROM export implemented; device verification pending**

- Build and export any supported game with one Compose command, without starting
  the emulator or touching saves. Reuse the existing source/ROM caches and copy
  only the verified ROM into the ignored `.cache/exports/pokemon-<game>/` folder.
- Import compiled ROMs into the existing SameBoy iPhone app using Files or AirDrop.
- Test the same builds on Mac and iPhone.
- Verify device controls, ROM import, saving, and overall play on a real iPhone;
  Mac verification alone does not establish device behavior.
- Keep ROMs, source checkouts, saves, and emulator artifacts local and ignored.

## Deferred — 3D exploration

Revisit modern 3D presentation after the original 2D game workflows and source
customizations are proven. Start with a small state bridge and scene prototype.
Architecture and delivery scope remain undecided.
