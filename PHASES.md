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

**Status: Complete**

### Phase 3A — Complete

- Begin a canonical new game in Red's House 2F.
- Implement Mom and the house flow.
- Add Oak's interception and scripted walk to the lab.
- Add reusable event flags, conditional dialog, and scripted movement.
- Add starter choice and a basic party.
- End the milestone before the rival battle.

### Phase 3B — Complete

- Complete: source-backed level-5 starter stats and moves, immutable Pokémon
  realization, and a standalone Python turn engine through fainting. Optional
  live ROM checks cover all granted starter stats, moves, and PP.
- Complete: story-integrated starter realization and the playable rival battle
  screen in both renderers, with authoritative HP/PP, ordered text, replay-safe
  turns, and canonical terminal win/loss results.
- Complete: experience/stat experience, level-6 stats and HP growth, the wallet
  and ¥175 reward, healing after either outcome, rival farewell/departure, and
  return to lab control with postbattle text and no repeated challenge.
- Complete: live PyBoy comparisons for all three starters' wins and losses,
  replaying observed decision bytes to validate turns and postbattle outcomes.
  See the reference-oracle documentation for coverage and evidence.

## Phase 4 — Route 1 and Viridian City

**Status: Future**

- Expand source-backed maps through Route 1 and Viridian City.
- Add wild encounters, ledges and terrain behavior, and Pokémon Center healing.

## Phase 5 — Game menus and persistence

**Status: Future**

- Add party, inventory, and trainer menus.
- Add versioned save and load support.
