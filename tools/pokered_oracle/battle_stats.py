"""Read granted starter bytes from the running ROM; compare the Python factory."""

from collections.abc import Callable

from backend.app.engine.pokemon import realize_starter
from backend.app.models.battle import BattleDefinition, DeterminantValues

from .errors import OracleError


def validate_granted_starter(
    definition: BattleDefinition, species: str, read: Callable[[str, int], int]
) -> None:
    dvs = DeterminantValues(
        attack_defense=read("wPartyMon1DVs", 0),
        speed_special=read("wPartyMon1DVs", 1),
    )
    expected = realize_starter(definition, species, dvs)
    observed: dict[str, object] = {
        "species_id": read("wPartyMon1Species", 0),
        "level": read("wPartyMon1Level", 0),
        "moves": tuple(read("wPartyMon1Moves", i) for i in range(4)),
        "pp": tuple(read("wPartyMon1PP", i) for i in range(4)),
        "stat_experience": tuple(read("wPartyMon1HPExp", i) for i in range(10)),
    }
    wanted: dict[str, object] = {
        "species_id": definition.species_named(species).species.id,
        "level": 5,
        "moves": (*(definition.move_named(move.constant).id for move in expected.moves), 0, 0),
        "pp": (*(move.pp for move in expected.moves), 0, 0),
        "stat_experience": (0,) * 10,
    }
    for field, label in (
        ("hp", "HP"),
        ("max_hp", "MaxHP"),
        ("attack", "Attack"),
        ("defense", "Defense"),
        ("speed", "Speed"),
        ("special", "Special"),
    ):
        observed[field] = read(f"wPartyMon1{label}", 0) * 256 + read(f"wPartyMon1{label}", 1)
        wanted[field] = expected.stats.hp if field == "max_hp" else getattr(expected.stats, field)
    differences = {
        field: (wanted[field], value) for field, value in observed.items() if value != wanted[field]
    }
    if differences:
        raise OracleError(f"granted {species} battle data differs (expected, ROM): {differences}")
