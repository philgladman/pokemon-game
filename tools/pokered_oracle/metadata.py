from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from backend.app.source.pokered.parsers import parse_rgbds_constants, require_constants

from .errors import OracleError

SUPPORTED_MAPS = {
    "PALLET_TOWN",
    "REDS_HOUSE_1F",
    "REDS_HOUSE_2F",
    "BLUES_HOUSE",
    "OAKS_LAB",
}
STORY_EVENTS = {
    "EVENT_FOLLOWED_OAK_INTO_LAB",
    "EVENT_FOLLOWED_OAK_INTO_LAB_2",
    "EVENT_OAK_ASKED_TO_CHOOSE_MON",
    "EVENT_GOT_STARTER",
    "EVENT_BATTLED_RIVAL_IN_OAKS_LAB",
    "EVENT_OAK_APPEARED_IN_PALLET",
}
STARTER_SPECIES = {"CHARMANDER", "SQUIRTLE", "BULBASAUR"}


@dataclass(frozen=True)
class SourceMetadata:
    maps_by_value: dict[int, str]
    events: dict[str, int]
    species_by_value: dict[int, str]

    @classmethod
    def read(cls, source_root: Path) -> SourceMetadata:
        map_text = (source_root / "constants/map_constants.asm").read_text(encoding="utf-8")
        map_values = {
            match.group(1): int(match.group(2), 16)
            for match in re.finditer(
                r"^\s*map_const\s+([A-Z0-9_]+),.*?;\s*\$([0-9A-Fa-f]{2})\s*$",
                map_text,
                re.MULTILINE,
            )
        }
        missing_maps = SUPPORTED_MAPS - map_values.keys()
        if missing_maps:
            raise OracleError(f"source map constants are missing: {sorted(missing_maps)}")

        event_values = require_constants(
            parse_rgbds_constants(
                (source_root / "constants/event_constants.asm").read_text(encoding="utf-8")
            ),
            STORY_EVENTS,
        )
        species_values = require_constants(
            parse_rgbds_constants(
                (source_root / "constants/pokemon_constants.asm").read_text(encoding="utf-8")
            ),
            STARTER_SPECIES,
        )
        return cls(
            maps_by_value={value: name for name, value in map_values.items()},
            events=event_values,
            species_by_value={value: name for name, value in species_values.items()},
        )

    def map_name(self, value: int) -> str:
        return self.maps_by_value.get(value, f"MAP_{value:02X}")

    def species_name(self, value: int) -> str | None:
        if value in (0, 0xFF):
            return None
        return self.species_by_value.get(value, f"SPECIES_{value:02X}")

    def active_events(self, event_bytes: bytes) -> tuple[str, ...]:
        return tuple(
            sorted(
                name
                for name, index in self.events.items()
                if index // 8 < len(event_bytes) and event_bytes[index // 8] & (1 << (index % 8))
            )
        )


FACING_BY_VALUE = {0x00: "south", 0x04: "north", 0x08: "west", 0x0C: "east"}


def normalize_facing(value: int) -> str:
    try:
        return FACING_BY_VALUE[value & 0x0C]
    except KeyError as error:  # pragma: no cover - bit mask makes this defensive
        raise OracleError(f"unsupported sprite facing value: {value:#04x}") from error
