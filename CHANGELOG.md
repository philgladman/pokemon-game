# Changelog

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
