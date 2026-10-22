from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from sameboy import rom_builder
from sameboy.games import GAMES, Game, configured_game, verify_artifacts

ROM = b"canonical fixture" * 30


@pytest.fixture
def source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Game:
    checkout = tmp_path / "source"
    checkout.mkdir()
    subprocess.run(["git", "init", "-q", str(checkout)], check=True)
    (checkout / "input.txt").write_text("canonical source\n")
    subprocess.run(["git", "-C", str(checkout), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(checkout),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    revision = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"])
    # A local fixture exercises real clone/fetch/archive without external network.
    real_git = rom_builder.git

    def fixture_git(path: Path, *args: str) -> bytes:
        monkeypatch.setenv("GIT_ALLOW_PROTOCOL", "file")
        return real_git(path, *args)

    monkeypatch.setattr(rom_builder, "git", fixture_git)
    return replace(
        GAMES["red"],
        repository=str(checkout),
        revision=revision.decode().strip(),
        sha1=hashlib.sha1(ROM).hexdigest(),
    )


def artifacts(game: Game, directory: Path) -> None:
    (directory / game.filename).write_bytes(ROM)
    (directory / game.symbols).write_text("debug symbols")


def test_export_uses_pinned_commit_not_worktree(source: Game, tmp_path: Path) -> None:
    checkout = Path(source.repository)
    (checkout / "input.txt").write_text("hidden edit")
    (checkout / "untracked").write_text("not source")
    exported = tmp_path / "exported"
    exported.mkdir()
    rom_builder.export_source(source, tmp_path / "sources", exported)
    assert (exported / "input.txt").read_text() == "canonical source\n"
    assert not (exported / "untracked").exists()
    assert (checkout / "input.txt").read_text() == "hidden edit"


def test_cached_source_fetches_but_keeps_pin(source: Game, tmp_path: Path) -> None:
    cache = tmp_path / "sources"
    first = tmp_path / "first"
    first.mkdir()
    rom_builder.export_source(source, cache, first)
    checkout = Path(source.repository)
    (checkout / "input.txt").write_text("newer source")
    subprocess.run(
        [
            "git",
            "-C",
            str(checkout),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qam",
            "newer",
        ],
        check=True,
    )
    second = tmp_path / "second"
    second.mkdir()
    rom_builder.export_source(source, cache, second)
    assert (second / "input.txt").read_text() == "canonical source\n"
    assert len([path for path in cache.iterdir() if path.is_dir()]) == 1


def test_wrong_revision_does_not_publish(source: Game, tmp_path: Path) -> None:
    game = replace(source, revision="0" * 40)
    with pytest.raises(rom_builder.BuildError, match="source fetch/export failed"):
        rom_builder.build_rom(game, tmp_path / "sources", tmp_path / "roms")
    assert not game.directory(tmp_path / "roms").exists()


def test_verified_build_is_cached_but_source_failure_still_fails_closed(
    source: Game, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output, sources = tmp_path / "roms", tmp_path / "sources"
    compilations: list[Path] = []

    def compile_fixture(game: Game, build: Path) -> None:
        compilations.append(build)
        assert (build / "input.txt").read_text() == "canonical source\n"
        artifacts(game, build)

    monkeypatch.setattr(rom_builder, "compile_rom", compile_fixture)
    rom = rom_builder.build_rom(source, sources, output)
    assert rom.read_bytes() == ROM
    assert rom_builder.build_rom(source, sources, output) == rom
    assert len(compilations) == 1
    Path(source.repository).rename(tmp_path / "unavailable")
    with pytest.raises(rom_builder.BuildError):
        rom_builder.build_rom(source, sources, output)
    assert rom.read_bytes() == ROM


def test_failed_build_preserves_other_versions(
    source: Game, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "roms"
    existing = output / "unrelated"
    existing.mkdir(parents=True)
    (existing / "keep").write_text("saved artifact")

    def fail(_game: Game, _build: Path) -> None:
        raise ValueError("ROM SHA-1 mismatch")

    monkeypatch.setattr(rom_builder, "compile_rom", fail)
    with pytest.raises(ValueError, match="SHA-1 mismatch"):
        rom_builder.build_rom(source, tmp_path / "sources", output)
    assert (existing / "keep").read_text() == "saved artifact"
    assert not source.directory(output).exists()


def test_wrong_hash_and_missing_symbols_fail(source: Game, tmp_path: Path) -> None:
    (tmp_path / source.filename).write_bytes(b"incorrect ROM")
    with pytest.raises(ValueError, match="SHA-1 mismatch"):
        verify_artifacts(source, tmp_path)
    (tmp_path / source.filename).write_bytes(ROM)
    with pytest.raises(ValueError, match="debug symbols"):
        verify_artifacts(source, tmp_path)
    (tmp_path / source.symbols).touch()
    with pytest.raises(ValueError, match="debug symbols"):
        verify_artifacts(source, tmp_path)


def test_publication_staging_failure_is_atomic(source: Game, tmp_path: Path) -> None:
    build, output = tmp_path / "build", tmp_path / "output"
    build.mkdir()
    (build / source.symbols).write_text("symbols")
    with pytest.raises(FileNotFoundError):
        rom_builder.publish(source, build, output)
    assert not output.exists()
    assert not list(tmp_path.glob(".rom-publish-*"))


@pytest.mark.parametrize("name", GAMES)
def test_catalog_selects_distinct_reproducible_builds(name: str) -> None:
    game = configured_game({"POKEMON_GAME": name})
    assert game.name == name
    assert game.target == name
    assert game.rgbds == "1.0.4"
    assert len(game.key) == 64
    assert game.key != replace(game, revision="0" * 40).key


@pytest.mark.parametrize(
    "environment",
    [
        {"POKEMON_GAME": "../red"},
        {"POKEMON_SOURCE_VERSION": "master"},
        {"POKEMON_ROM_SHA1": "invalid"},
        {"POKEMON_SOURCE_REPO": "file:///tmp/source"},
        {"POKEMON_SOURCE_REPO": "https://user:secret@example.com/source.git"},
    ],
)
def test_unsafe_configuration_is_rejected(environment: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        configured_game(environment)


def test_cli_config_failure_is_structured(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("POKEMON_GAME", "invalid")
    monkeypatch.setattr(sys, "argv", ["rom_builder"])
    assert rom_builder.main() == 1
    message = json.loads(capsys.readouterr().out)
    assert message["event"] == "rom_build"
    assert message["outcome"] == "failure"
