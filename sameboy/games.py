"""Pinned game builds shared by source preparation and emulator startup."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Game:
    name: str
    repository: str
    revision: str
    target: str
    filename: str
    sha1: str
    rgbds: str = "1.0.4"

    @property
    def symbols(self) -> str:
        return Path(self.filename).with_suffix(".sym").name

    @property
    def key(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()

    def directory(self, root: Path) -> Path:
        return root / self.name / self.key


GAMES = {
    name: Game(name, f"https://github.com/pret/{repository}.git", revision, name, filename, sha1)
    for name, repository, revision, filename, sha1 in (
        (
            "red",
            "pokered",
            "af519899719f0754965776faac0e836a3b906e6d",
            "pokered.gbc",
            "ea9bcae617fdf159b045185467ae58b2e4a48b9a",
        ),
        (
            "blue",
            "pokered",
            "af519899719f0754965776faac0e836a3b906e6d",
            "pokeblue.gbc",
            "d7037c83e1ae5b39bde3c30787637ba1d4c48ce2",
        ),
        (
            "yellow",
            "pokeyellow",
            "b6696f24b3be84fe64cf702f5a15ba40c66b7f39",
            "pokeyellow.gbc",
            "cc7d03262ebfaf2f06772c1a480c7d9d5f4a38e1",
        ),
        (
            "gold",
            "pokegold",
            "fc702b6d922aecce274782d68bba8639936a1182",
            "pokegold.gbc",
            "d8b8a3600a465308c9953dfa04f0081c05bdcb94",
        ),
        (
            "silver",
            "pokegold",
            "fc702b6d922aecce274782d68bba8639936a1182",
            "pokesilver.gbc",
            "49b163f7e57702bc939d642a18f591de55d92dae",
        ),
        (
            "crystal",
            "pokecrystal",
            "5c877ef55197039c9676e8e3eec6d254b1c40fe8",
            "pokecrystal.gbc",
            "f4cd194bdee0d04ca4eac29e09b8e4e9d818c133",
        ),
    )
}


def configured_game(environment: Mapping[str, str] | None = None) -> Game:
    environment = os.environ if environment is None else environment
    name = environment.get("POKEMON_GAME", "red")
    if name not in GAMES:
        raise ValueError(f"POKEMON_GAME must be one of: {', '.join(GAMES)}")
    original = GAMES[name]
    game = replace(
        original,
        repository=environment.get("POKEMON_SOURCE_REPO") or original.repository,
        revision=environment.get("POKEMON_SOURCE_VERSION") or original.revision,
        sha1=environment.get("POKEMON_ROM_SHA1") or original.sha1,
    )
    url = urlsplit(game.repository)
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username is not None
        or url.password is not None
        or url.query
        or url.fragment
        or not url.path.strip("/")
        or any(character.isspace() for character in game.repository)
    ):
        raise ValueError("POKEMON_SOURCE_REPO must be a credential-free HTTPS repository URL")
    if not re.fullmatch(r"[0-9a-f]{40}", game.revision):
        raise ValueError("POKEMON_SOURCE_VERSION must be a full lowercase 40-character commit")
    if not re.fullmatch(r"[0-9a-f]{40}", game.sha1):
        raise ValueError("POKEMON_ROM_SHA1 must be a lowercase 40-character SHA-1")
    return game


def verify_artifacts(game: Game, directory: Path) -> Path:
    rom = directory / game.filename
    if not rom.is_file() or hashlib.sha1(rom.read_bytes()).hexdigest() != game.sha1:
        raise ValueError("ROM SHA-1 mismatch or missing artifact")
    symbols = directory / game.symbols
    if not symbols.is_file() or not symbols.stat().st_size:
        raise ValueError("build did not generate debug symbols")
    return rom
