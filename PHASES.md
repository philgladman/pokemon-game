# Project phases

This is a living scope reference, not a complete delivery timeline. It stops at
Phase 5 and intentionally includes no dates. See the [changelog](CHANGELOG.md)
for implementation details.

## Phase 1 — Pallet Town vertical slice

**Status: Complete**

- Python-authoritative movement, collision, interactions, dialog, and warps.
- Initial Three.js renderer plus the Docker and test baseline.

## Phase 2 — Source-backed Pallet gameplay

**Status: Complete**

- Runtime data from a pinned `pret/pokered` source checkout.
- Five Pallet maps with canonical graphics and the retro renderer.
- Source-faithful movement, transitions, and text, with optional 3D rendering.

## Phase 3 — Pallet opening story

**Status: Current (Phase 3B)**

### Phase 3A — Complete

- Begin a canonical new game in Red's House 2F.
- Implement Mom and the house flow.
- Add Oak's interception and scripted walk to the lab.
- Add reusable event flags, conditional dialog, and scripted movement.
- Add starter choice and a basic party.
- End the milestone before the rival battle.

### Phase 3B — Current milestone

- Add the first rival battle: stats, moves, turn flow, battle screen, damage,
  fainting, experience, and victory.

## Phase 4 — Route 1 and Viridian City

**Status: Future**

- Expand source-backed maps through Route 1 and Viridian City.
- Add wild encounters, ledges and terrain behavior, and Pokémon Center healing.

## Phase 5 — Game menus and persistence

**Status: Future**

- Add party, inventory, and trainer menus.
- Add versioned save and load support.
