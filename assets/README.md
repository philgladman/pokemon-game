# Assets

Phase 1 renders original geometric primitives in Three.js and contains no
Pokémon ROM, ripped graphics, music, or other proprietary game media. Future
assets belong in the typed paths represented by the game-data schema.

This root directory is the canonical asset source. FastAPI serves it at
`/assets`, and both Vite and Nginx proxy that route. A manifest URL such as
`/assets/models/tree.glb` therefore maps to `assets/models/tree.glb` in every
supported runtime without copying files into the frontend.

Compiled browser JavaScript and CSS use `/frontend/`, not `/assets/`, so they
cannot collide with this gameplay-asset namespace.
