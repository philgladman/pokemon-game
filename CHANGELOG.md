# Changelog

## Unreleased

- Added a separate loopback-only SameBoy 1.0.4 Docker/noVNC workflow with
  source-built ROM input, native CGB compatibility color, project-scoped save
  volumes, graceful SDL shutdown, and opt-in bounded PCM browser audio.
- Documented controls, baseline/modified profile isolation, save retention,
  audio acceptance limits, and startup/health troubleshooting.
- Revised the phase roadmap toward an original 2D SameBoy/Docker browser
  workflow, followed by source-customized ROMs and existing-app iPhone play;
  preserved the completed recreation as reference and deferred 3D exploration.
- Added a standalone, immutable Python foundation for the first rival battle:
  source-parsed level-5 starter data, player/trainer DVs and realized stats,
  starting moves/PP, and rival counter-starter mapping.
- Added deterministic turn resolution with injected random bytes, source-order
  rival selection and AI draws, speed ties, critical hits, integer damage,
  accuracy, Growl/Tail Whip, PP exhaustion, Struggle/recoil, and fainting.
- Added optional `oracle check --battle-stats` comparisons for all three granted
  starters' actual ROM DVs, stats, moves, PP, level, and stat experience.
- Added optional `oracle check --battle` independent live turn and outcome
  comparisons for all three starters' wins and losses, replaying observed RNG
  decision bytes into Python and retaining partial traces on validation failure.
- Connected the source-authored rival challenge to a shared retro/3D browser
  battle overlay, preserving the player's once-realized starter through combat.
  Added source starter front/back PNGs, canonical move names and focused dynamic
  battle text translation, server-owned HP/PP presentation frames, acknowledged
  event batches, replay-safe turn tokens, keyboard/pointer controls and artwork
  retry/disconnect handling.
- Completed first-battle outcomes: source experience/stat experience, level-6
  stats and HP growth, the ¥175 reward and wallet, and canonical win/loss text.
  Per-frame level/stat presentation prevents final stats appearing early.
- Acknowledging the terminal batch now resumes the lab script: heal on either
  outcome, set the battled event, show the farewell, animate the rival leaving,
  and restore control. Oak uses postbattle text and the challenge cannot repeat.

## 0.3.0 - 2026-10-19

- Added an optional, headless PyBoy reference oracle that builds the exact
  pinned Red ROM with RGBDS 1.0.4 in an ignored cache, verifies its canonical
  SHA-1 and symbols, and records deterministic semantic traces independently of
  the normal application checks.
- Expanded the oracle across all Phase 3A behavior: source-timed held movement,
  house transitions, Pallet signs and wandering NPCs, both Oak-intercept
  columns, lab entry/positioning, and every starter/counter-starter branch using
  shared semantic drivers and in-memory source/runtime checkpoints.
- Compared complete observed Oak/lab movement paths against runtime cues, both
  house exit columns and their warp policy, and starter choice-open state; added
  mutation regressions and retained partial oracle traces on failed checks.
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
