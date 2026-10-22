from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import BinaryIO

import pytest

from sameboy import rom_builder
from sameboy.games import GAMES


def test_export_anchors_publication_when_directory_is_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = b"verified ROM fixture"
    game = replace(GAMES["red"], sha1=hashlib.sha1(content).hexdigest())
    rom = tmp_path / game.filename
    rom.write_bytes(content)
    root = tmp_path / "exports"
    directory = root / "pokemon-red"
    held = root / "original-directory"
    outside = tmp_path / "outside"
    outside.mkdir()
    protected = outside / game.filename
    protected.write_bytes(b"do not change")
    copy = rom_builder.shutil.copyfileobj

    def swap_directory(source: BinaryIO, destination: BinaryIO) -> None:
        directory.rename(held)
        directory.symlink_to(outside, target_is_directory=True)
        copy(source, destination)

    monkeypatch.setattr(rom_builder.shutil, "copyfileobj", swap_directory)
    rom_builder.export_rom(game, rom, root)
    assert protected.read_bytes() == b"do not change"
    assert (held / game.filename).read_bytes() == content
    assert list(held.iterdir()) == [held / game.filename]
    assert list(outside.iterdir()) == [protected]


def test_concurrent_exports_publish_complete_files(tmp_path: Path) -> None:
    content = b"verified ROM fixture" * 100_000
    game = replace(GAMES["red"], sha1=hashlib.sha1(content).hexdigest())
    rom = tmp_path / game.filename
    rom.write_bytes(content)
    root = tmp_path / "exports"

    with ThreadPoolExecutor(max_workers=4) as executor:
        exports = list(executor.map(lambda _: rom_builder.export_rom(game, rom, root), range(8)))

    assert len(set(exports)) == 1
    assert exports[0].read_bytes() == content
    assert list(exports[0].parent.iterdir()) == [exports[0]]
    assert exports[0].stat().st_mode & 0o777 == 0o644
