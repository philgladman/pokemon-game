"""Fetch pinned source and atomically publish verified Gen 1/2 game builds."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import tarfile
import tempfile
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sameboy.games import GAMES, Game, configured_game, verify_artifacts


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
                **fields,
            }
        ),
        flush=True,
    )


def git(source: Path, *arguments: str) -> bytes:
    try:
        return subprocess.run(
            ["git", "-c", "protocol.file.allow=never", "-C", str(source), *arguments],
            check=True,
            capture_output=True,
            timeout=300,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        ).stdout
    except (OSError, subprocess.SubprocessError) as error:
        raise BuildError("source fetch/export failed; check network and pinned revision") from error


def export_source(game: Game, sources: Path, destination: Path) -> None:
    sources.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(game.repository.encode()).hexdigest()
    checkout = sources / key
    with (sources / f"{key}.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not checkout.exists():
            with tempfile.TemporaryDirectory(prefix=".source-", dir=sources) as temporary:
                staged = Path(temporary) / "repository"
                git(sources, "clone", "--mirror", "--", game.repository, str(staged))
                os.replace(staged, checkout)
        else:
            git(
                checkout,
                "fetch",
                "--prune",
                "origin",
                "+refs/heads/*:refs/heads/*",
                "+refs/tags/*:refs/tags/*",
            )
        revision = git(checkout, "rev-parse", "--verify", f"{game.revision}^{{commit}}")
        if revision.decode().strip() != game.revision:
            raise BuildError("source did not resolve to configured commit")
        exported = git(checkout, "archive", "--format=tar", game.revision)
    with tarfile.open(fileobj=io.BytesIO(exported), mode="r:") as archive:
        archive.extractall(destination, filter="data")
    log("source_export", "success", game=game.name, revision=game.revision)


def compile_rom(game: Game, build: Path) -> None:
    subprocess.run(
        ["make", "-B", "-C", str(build), "DEBUG=1", game.target], check=True, timeout=600
    )
    verify_artifacts(game, build)


def publish(game: Game, build: Path, output: Path) -> None:
    with tempfile.TemporaryDirectory(prefix=".rom-publish-", dir=output.parent) as temporary:
        staged = Path(temporary) / "artifacts"
        staged.mkdir(mode=0o755)
        for name in (game.symbols, game.filename):
            shutil.copyfile(build / name, staged / name)
            (staged / name).chmod(0o644)
        os.replace(staged, output)


def build_rom(game: Game, sources: Path, output: Path) -> Path:
    directory = game.directory(output)
    directory.parent.mkdir(parents=True, exist_ok=True)
    with (directory.parent / f".{game.key}.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with tempfile.TemporaryDirectory(prefix=f"{game.name}-build-") as temporary:
            build = Path(temporary)
            export_source(game, sources, build)
            if directory.exists():
                rom = verify_artifacts(game, directory)
                log("rom_build", "cached", game=game.name, output=str(rom))
                return rom
            compile_rom(game, build)
            publish(game, build, directory)
        rom = directory / game.filename
        log("rom_build", "success", game=game.name, output=str(rom), sha1=game.sha1)
        return rom


def export_rom(game: Game, rom: Path, root: Path) -> Path:
    if game.name not in GAMES or game.filename != GAMES[game.name].filename:
        raise ValueError("export requires a catalog game and filename")
    directory = root / f"pokemon-{game.name}"
    destination = directory / game.filename
    if root.is_symlink() or directory.is_symlink() or destination.is_symlink():
        raise ValueError("export paths must not be symbolic links")
    root.mkdir(parents=True, exist_ok=True)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        with suppress(FileExistsError):
            os.mkdir(directory.name, mode=0o755, dir_fd=root_fd)
        directory_fd = os.open(
            directory.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd
        )
    finally:
        os.close(root_fd)
    staged = f".rom-export-{uuid4().hex}"
    staged_created = False
    try:
        try:
            existing = os.stat(game.filename, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            existing = None
        if existing is not None and stat.S_ISLNK(existing.st_mode):
            raise ValueError("export paths must not be symbolic links")
        # Anchor staging and publication to the opened directory, not a path that
        # another process could replace with a symlink during the export.
        staged_fd = os.open(
            staged,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory_fd,
        )
        staged_created = True
        with os.fdopen(staged_fd, "w+b") as output, rom.open("rb") as source:
            shutil.copyfileobj(source, output)
            output.flush()
            output.seek(0)
            if hashlib.file_digest(output, "sha1").hexdigest() != game.sha1:
                raise ValueError("exported ROM SHA-1 mismatch")
            os.fchmod(output.fileno(), 0o644)
        os.replace(staged, game.filename, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
    finally:
        try:
            if staged_created:
                with suppress(FileNotFoundError):
                    os.unlink(staged, dir_fd=directory_fd)
        finally:
            os.close(directory_fd)
    log("rom_export", "success", game=game.name, output=str(destination), sha1=game.sha1)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, default=Path("/sources"))
    parser.add_argument("--output", type=Path, default=Path("/roms"))
    parser.add_argument(
        "--export", type=Path, help="also export the verified ROM to a local folder"
    )
    arguments = parser.parse_args()
    try:
        game = configured_game()
        rom = build_rom(game, arguments.sources, arguments.output)
    except (BuildError, ValueError, OSError, subprocess.SubprocessError, tarfile.TarError) as error:
        log("rom_build", "failure", output=str(arguments.output), error=str(error))
        return 1
    if arguments.export is not None:
        try:
            export_rom(game, rom, arguments.export)
        except (ValueError, OSError) as error:
            log(
                "rom_export",
                "failure",
                game=game.name,
                output=str(arguments.export),
                error=str(error),
            )
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
