# Project phases

This is a living scope reference, not a complete delivery timeline. It stops at
Phase 5 and intentionally includes no dates. See the [changelog](CHANGELOG.md)
for implementation details.

## Direction change

Phases 1–3 record completed work on the Python/browser recreation. That runtime,
its renderers, and the PyBoy reference oracle remain preserved as reference work;
the recreation is not pixel-perfect. The current direction is to run the
original 2D game in SameBoy through Docker and a Mac browser, then customize the
game's source. The separate SameBoy/Docker workflow is implemented; see
[setup and acceptance limits](docs/sameboy.md).

The former Route 1/Viridian City expansion and game-menu/save-system recreation
plans are superseded, not completed. Those features already exist in the
original ROM; rebuilding them in Python is no longer the next milestone.

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

## Phase 4 — Original 2D game through SameBoy and Docker

**Status: Current — implemented; automated and browser verification complete**

- Compile the original Red ROM from the source checkout and run it in SameBoy's
  Linux SDL frontend inside Docker.
- Expose the virtual display through VNC/noVNC for play in a Mac browser. This
  workflow requires no native Mac application.
- Stream container audio separately through bounded PCM WebSocket/AudioWorklet
  transport, enabled by a browser gesture. Nonzero PCM and browser worklet
  output, bounded buffering, and reconnect behavior are verified; audio quality
  still needs manual listening.
- Persist in-game saves independently of disposable containers and ROM builds.
  Keep ROMs, saves, and emulator-generated artifacts in ignored local storage;
  keep baseline and modified-game profiles separate so saves are not mixed.

Verified: the source ROM compiles, the documented Docker workflow launches a
playable original 2D game in the Mac browser, and controls work. An ordinary
in-game save survives container restart and recreation, and Continue reloads
the correct player and location; baseline and modified profiles remain isolated.
Audio transport, nonzero worklet output, and reconnect are verified with muted
browser output. Listening quality remains a separate manual acceptance check.

## Phase 5 — Custom Pokémon builds and iPhone play

**Status: Future**

- Patch and compile Pokémon game source, rather than modifying the emulator, to
  customize encounters and remove the need to trade for trade evolutions. Agree
  the exact encounter changes and replacement evolution rules later.
- Start with Red. Blue and Yellow support is a goal; Yellow needs its own source
  project rather than being treated as a Red build variant.
- Import the compiled ROM into the existing SameBoy iPhone app using Files or
  AirDrop. A project-owned iPhone app is not the first step.
- Test the same compiled ROM on the Mac workflow and iPhone. Validate actual
  device controls, import, saving, and overall play separately from ROM-level
  behavior; Mac success alone does not establish the iPhone experience.
- Keep compiled ROMs and saves local and ignored; do not commit them.

Acceptance: an agreed custom Red build demonstrates its encounter and evolution
changes, runs in both workflows, and passes separate actual-device iPhone UX
checks. Preserve separate baseline and modified-game save profiles.

## Deferred — 3D exploration

Revisit 3D only after the original 2D workflow and source-customization approach
are proven. Begin with a small state bridge and scene prototype. Whether that
eventually belongs in a fork or a new application remains undecided; it is not
an additional committed phase or a whole-project roadmap.
