# Changelog

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
