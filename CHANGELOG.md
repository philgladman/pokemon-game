# Changelog

## Unreleased

- Added an export-only Compose workflow for all six games, reusing the existing
  source fetch/build caches without starting the player or mounting save data.
  Verified ROMs are atomically exported to ignored `.cache/exports/pokemon-<game>/`
  folders for local transfer; failed exports preserve previous complete files.
- Use port 8080 by default for browser access and internal readiness checks;
  `SAMEBOY_PORT` still overrides the loopback browser port.
- Added one-command Compose startup for Red, Blue, Yellow, Gold, Silver, and
  Crystal using pinned, automatically fetched source and verified ROM checksums.
- Cache source repositories and immutable game/configuration artifacts in Docker
  volumes; failed fetches/builds stop startup without overwriting existing ROMs.
- Isolate saves, preferences, states, and RTC data per game while preserving the
  existing Red save and `pokemon-baseline_profile` volume.
- Use default `compose.yaml` and a separate optional custom-ROM overlay; document
  source/revision/checksum overrides and locally built image stages.
- Added an explicit Docker ROM-builder service using pinned RGBDS 1.0.4. It
  exports clean pinned source into temporary storage, verifies canonical Red,
  and publishes ROM and symbol files without replacing artifacts on build
  failure. Concurrent builds serialize and unrelated output files are retained.
- Added a loopback-only SameBoy 1.0.4 Docker/noVNC player with CGB compatibility
  color, project-scoped saves, graceful SDL shutdown, and opt-in bounded PCM audio.
- Documented source setup, browser controls, baseline and modified profile
  isolation, save retention, audio acceptance limits, and health troubleshooting.
- Move compiled artifacts from host `.cache/roms/pokered/` storage into the
  project-scoped Docker `roms` volume; existing host files are left untouched.
- Added Python and dependency-free Node.js checks for the builder, runtime,
  keyboard controls, audio buffering, and resampling.
