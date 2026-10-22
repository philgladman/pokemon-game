from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from sameboy import run
from sameboy.games import GAMES


@pytest.mark.parametrize("name", GAMES)
def test_each_game_preserves_saves_rtc_and_preferences(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    roms, profile = tmp_path / "roms", tmp_path / "profile"
    profile.mkdir()
    contents = bytes(range(256)) * 4
    game = replace(GAMES[name], sha1=hashlib.sha1(contents).hexdigest())
    directory = game.directory(roms)
    directory.mkdir(parents=True)
    (directory / game.filename).write_bytes(contents)
    (directory / game.symbols).write_text("debug symbols")
    expected = profile if name == "red" else profile / "games" / name
    expected.mkdir(parents=True, exist_ok=True)
    sentinels = {
        expected / "game.sav": b"battery RAM",
        expected / "game.rtc": b"clock state",
        expected / "game.s1": b"save state",
        expected / ".config" / "sameboy" / "preferences.bin": b"preferences",
        profile / "game.sav": b"existing Red battery RAM",
    }
    for path, value in sentinels.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
    if name == "red":
        (profile / "game.gb").symlink_to("/rom/pokered.gbc")
    monkeypatch.delenv("SAMEBOY_ROM", raising=False)
    monkeypatch.setattr(run, "configured_game", lambda: game)
    link, selected = run.prepare_game(roms, profile)
    assert selected == expected
    assert link == expected / "game.gb"
    assert link.resolve() == directory / game.filename
    assert run.prepare_game(roms, profile) == (link, selected)
    for path, value in sentinels.items():
        assert path.read_bytes() == value


def test_corrupt_rom_fails_before_profile_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    game = GAMES["gold"]
    roms, profile = tmp_path / "roms", tmp_path / "profile"
    directory = game.directory(roms)
    directory.mkdir(parents=True)
    (directory / game.filename).write_bytes(b"bad ROM")
    (directory / game.symbols).write_text("symbols")
    profile.mkdir()
    monkeypatch.delenv("SAMEBOY_ROM", raising=False)
    monkeypatch.setattr(run, "configured_game", lambda: game)
    with pytest.raises(ValueError, match="SHA-1"):
        run.prepare_game(roms, profile)
    assert not list(profile.iterdir())


@pytest.mark.parametrize("destination", ["outside", "root", "other-game"])
def test_symlinked_profile_cannot_alias_another_game(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, destination: str
) -> None:
    profile = tmp_path / "profile"
    (profile / "games").mkdir(parents=True)
    target = {
        "outside": tmp_path / "elsewhere",
        "root": profile,
        "other-game": profile / "games" / "silver",
    }[destination]
    target.mkdir(parents=True, exist_ok=True)
    (profile / "games" / "gold").symlink_to(target)
    rom = tmp_path / "custom.gb"
    rom.write_bytes(bytes(0x150))
    monkeypatch.setenv("SAMEBOY_ROM", str(rom))
    monkeypatch.setattr(run, "configured_game", lambda: GAMES["gold"])
    with pytest.raises(RuntimeError, match="profile"):
        run.prepare_game(tmp_path / "roms", profile)
    assert not (target / "game.gb").exists()


def test_games_parent_symlink_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()
    target = profile / "aliases"
    target.mkdir()
    (profile / "games").symlink_to(target)
    rom = tmp_path / "custom.gb"
    rom.write_bytes(bytes(0x150))
    monkeypatch.setenv("SAMEBOY_ROM", str(rom))
    monkeypatch.setattr(run, "configured_game", lambda: GAMES["blue"])
    with pytest.raises(RuntimeError, match="profile"):
        run.prepare_game(tmp_path / "roms", profile)
    assert not list(target.iterdir())


@pytest.mark.parametrize("occupied", ["file", "unmanaged-symlink"])
def test_unmanaged_game_path_remains_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, occupied: str
) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()
    rom = tmp_path / "custom.gb"
    rom.write_bytes(bytes(0x150))
    game_path = profile / "game.gb"
    if occupied == "file":
        game_path.write_bytes(b"user data")
    else:
        game_path.symlink_to("/unmanaged/other.gb")
    monkeypatch.setenv("SAMEBOY_ROM", str(rom))
    monkeypatch.setattr(run, "configured_game", lambda: GAMES["red"])
    with pytest.raises(RuntimeError, match="managed ROM symlink"):
        run.prepare_game(tmp_path / "roms", profile)
    if occupied == "file":
        assert game_path.read_bytes() == b"user data"
    else:
        assert game_path.readlink() == Path("/unmanaged/other.gb")
