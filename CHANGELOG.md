# Changelog

## Unreleased

- Added an explicit Docker ROM-builder service using pinned RGBDS 1.0.4. It
  exports clean pinned source into temporary storage, verifies canonical Red,
  and publishes ROM and symbol files without replacing artifacts on build
  failure. Concurrent builds serialize and unrelated output files are retained.
- Added a loopback-only SameBoy 1.0.4 Docker/noVNC player with CGB compatibility
  color, project-scoped saves, graceful SDL shutdown, and opt-in bounded PCM audio.
- Documented source setup, browser controls, baseline and modified profile
  isolation, save retention, audio acceptance limits, and health troubleshooting.
- Store compiled Red artifacts under ignored `.cache/roms/pokered/`.
- Added Python and dependency-free Node.js checks for the builder, runtime,
  keyboard controls, audio buffering, and resampling.
