"""Build the canonical Red ROM without a host Python or RGBDS installation."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import io
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path

PINNED_REVISION = "af519899719f0754965776faac0e836a3b906e6d"
RED_SHA1 = "ea9bcae617fdf159b045185467ae58b2e4a48b9a"
ARTIFACTS = ("pokered.sym", "pokered.gbc")


class BuildError(RuntimeError):
    """An unsuccessful build that must not replace previous artifacts."""


def log(event: str, outcome: str, **fields: str) -> None:
    print(
        json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "source": "rom_builder",
                "event": event,
                "outcome": outcome,
                "revision": PINNED_REVISION,
                **fields,
            }
        ),
        flush=True,
    )


def git(source: Path, *arguments: str) -> bytes:
    try:
        return subprocess.run(
            ["git", "-c", f"safe.directory={source}", "-C", str(source), *arguments],
            check=True,
            capture_output=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        raise BuildError(
            "source validation/export failed; use a clean pinned checkout in external/pokered"
        ) from error


def export_source(source: Path, destination: Path) -> None:
    if git(source, "rev-parse", "HEAD").decode().strip() != PINNED_REVISION:
        raise BuildError(f"source HEAD must be {PINNED_REVISION}")
    # Diff the canonical index as well as the worktree; untracked files are not inputs.
    git(source, "diff", "--quiet", "--cached", PINNED_REVISION, "--")
    git(source, "diff", "--quiet", "--")
    exported = git(source, "archive", "--format=tar", PINNED_REVISION)
    with tarfile.open(fileobj=io.BytesIO(exported), mode="r:") as archive:
        archive.extractall(destination, filter="data")


def compile_rom(build: Path) -> None:
    subprocess.run(["make", "-B", "-C", str(build), "DEBUG=1", "red"], check=True)
    rom = build / "pokered.gbc"
    actual = hashlib.sha1(rom.read_bytes()).hexdigest()
    if actual != RED_SHA1:
        raise BuildError(f"canonical ROM SHA-1 mismatch: expected {RED_SHA1}, got {actual}")
    if not (build / "pokered.sym").is_file() or not (build / "pokered.sym").stat().st_size:
        raise BuildError("build did not generate debug symbols")


def publish(build: Path, output: Path) -> None:
    # Stage both files on the output filesystem before replacing either one. The
    # ROM is the final publication marker; no partial ROM is ever visible.
    with tempfile.TemporaryDirectory(prefix=".rom-publish-", dir=output) as staging:
        staged = Path(staging)
        for name in ARTIFACTS:
            shutil.copyfile(build / name, staged / name)
            (staged / name).chmod(0o644)
        for name in ARTIFACTS:
            os.replace(staged / name, output / name)


def build_rom(source: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    with (output / ".rom-builder.lock").open("a") as lock:
        log("build_lock", "waiting", output=str(output))
        fcntl.flock(lock, fcntl.LOCK_EX)
        with tempfile.TemporaryDirectory(prefix="pokered-build-") as temporary:
            build = Path(temporary)
            export_source(source, build)
            log("source_export", "success", source_path=str(source))
            compile_rom(build)
            publish(build, output)
        log("rom_build", "success", output=str(output), sha1=RED_SHA1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("/source"))
    parser.add_argument("--output", type=Path, default=Path("/output"))
    arguments = parser.parse_args()
    try:
        build_rom(arguments.source, arguments.output)
    except (BuildError, OSError, subprocess.CalledProcessError, tarfile.TarError) as error:
        log("rom_build", "failure", output=str(arguments.output), error=str(error))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
