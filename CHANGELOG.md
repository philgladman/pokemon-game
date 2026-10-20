# Changelog

## 0.3.0 - 2026-10-19

- Added an optional, headless PyBoy reference oracle that builds the exact
  pinned Red ROM with RGBDS 1.0.4 in an ignored cache, verifies its canonical
  SHA-1 and symbols, and records deterministic semantic traces independently of
  the normal application checks.
- Added the source-backed Pallet opening story from the canonical new-game warp
  through starter selection, stopping at a typed boundary before the rival battle.
- Added an immutable, provenance-bearing trigger/condition/command story graph
  and a session-local Python runner for event flags, mutable actors, conditional
  dialog, choices, party state, and server-authored multi-actor movement cues.
- Parsed and validated the pinned source's event constants, initial visibility,
  story text, plain and RLE movement, starter IDs/names, counter-starter mapping,
  and runtime species-name text behavior with explicit source-drift failures.
- Added instance-correlated, replay-safe choices plus cue and transition
  acknowledgements, shared browser choice controls, and scripted movement in
  both renderers without bypassing the existing map fade; dialog and choice
  overlays reflect each cue snapshot before its completion-gated animation.
- Preserved source ordering for starter selection versus party grants, Oak's
  Pallet escort (including backward-consumed simulated joypad paths and the
  on-step lab warp that interrupts the remaining buffered input), lab actor
  facings, rival starter receipt, and the rival's approach immediately before
  the Phase 3B boundary.
- Kept rival battle state unset and made its trigger an explicit, non-skippable
  Phase 3B boundary.

## 0.2.0 - 2026-10-19

- Replaced checked-in imported YAML/generated JSON and handwritten Pallet
  content with a configurable live `PokeredSource` provider.
- Added focused, provenance-preserving parsers for the five Pallet maps,
  source graphics, collision, objects, background events, visibility, text,
  connections, and warps including `LAST_MAP`.
- Made the 160×144 source-graphics Canvas renderer the default and isolated the
  existing Three.js renderer behind `?renderer=3d`.
- Added an allowlisted source-asset endpoint without copying upstream graphics
  into this repository.
- Kept Python authoritative for movement and interaction, with unsupported
  conditional source scripts reported explicitly.
- Updated Docker, local setup, checks, tests, and ignore rules for the external
  runtime source model.
- Separated renderer-neutral logical snapshots from retro source-resource
  projections, while preserving the 3D manifest, GLB fallback, shadows, and
  interpolated movement behind its opt-in adapter.
- Resolved source text control tokens at dialog execution time with configurable
  normalized player/rival names.
- Replaced inferred `LAST_MAP` behavior with canonical indoor-group metadata and
  added round-trip coverage for every Pallet building and Red's House stairs.
- Made pinned source revision validation work in the minimal backend image
  without a Git executable by reading and validating checkout metadata directly.
- Added Git-index and tracked-worktree integrity validation so a dirty checkout
  cannot be presented as the pinned source revision; untracked files remain
  intentionally allowed.
- Restored the original configurable Three.js appearance manifest and canonical
  `/assets` GLB pipeline behind separate, cached renderer-resource endpoints.
- Corrected the pinned player sprite's directional frame rows and east/west
  mirroring, and added eight 2-pixel advances per tile with one walking pose per
  tile and alternating feet across continuous movement.
- Added transport-acknowledged held-key movement with source direction priority,
  dialog/focus/disconnect safety, blocked-move throttling, and a shared retro/3D
  movement cadence.
- Matched overworld neutral-input turn behavior: a changed-direction tap only
  turns, a held turn resamples after about 34 ms, and successful movement keeps
  a 268 ms tile cadence without the menu-only 502 ms repeat delay.
- Distinguished on-step warps from outward boundary exits, including paired-door
  sideways movement and the source-like automatic outdoor step south.
- Added renderer-neutral four-stage map fades that gate input until either
  renderer has applied the transitioned snapshot, with asset-failure recovery.

## 0.1.0 - 2026-10-07

- Added the Phase 1 Pallet Town and player's-house vertical slice.
- Added deterministic `pret/pokered` map/collision importing and validated data
  compilation.
- Added server-authoritative movement, collision, NPC dialog, and atomic map
  transitions over a typed WebSocket protocol.
- Added the Three.js TypeScript client, Docker Compose deployment, and automated
  backend/frontend checks.
- Added strict, duplicate-safe YAML validation and resilient malformed-message
  handling.
- Made transition destinations source-derived from map constants and warp
  indices, with explicit context for `LAST_MAP`.
- Separated gameplay appearance references from the primitive/GLB asset
  manifest.
- Added one canonical root asset tree served through the same `/assets` route
  in local Vite development and Docker/Nginx.
- Isolated generated frontend bundles under `/frontend/` so `/assets/` remains
  exclusively available for canonical gameplay assets.
- Reject unreachable transition/NPC overlaps and key/embedded-ID mismatches in
  runtime registries during model validation.
