# Project-owned assets

These assets belong to the [legacy recreation](../docs/legacy-recreation.md),
not the current SameBoy workflow. The source-built ROM supplies SameBoy's
graphics; no replacement 2D or 3D assets are needed to play it.

This is the canonical root for original or appropriately licensed Version 2
assets. FastAPI serves it at `/assets`, and both Vite and Nginx proxy that route,
so a 3D manifest URL such as `/assets/models/tree.glb` resolves identically in
local development and Docker. The Three.js asset factory keeps the configured
primitive visible if a GLB cannot be loaded.

Version 1 reads source graphics from the ignored `external/pokered` checkout
through the separate, allowlisted `/source-assets` endpoint. It does not copy
those graphics here or into Git history.
