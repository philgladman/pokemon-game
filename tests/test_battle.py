from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.engine.battle import _damage, _effective_stat, _rival_move, resolve_turn
from backend.app.engine.pokemon import (
    calculate_starter_stats,
    create_rival_battle,
    generate_player_starter,
    realize_starter,
)
from backend.app.models.battle import (
    BattleDefinition,
    BattleState,
    DeterminantValues,
    MoveCommand,
)
from backend.app.source.pokered import PokeredSource


class Bytes:
    def __init__(self, *values: int) -> None:
        self.values: Iterator[int] = iter(values)
        self.drawn: list[int] = []

    def __call__(self) -> int:
        value = next(self.values)
        self.drawn.append(value)
        return value


@pytest.fixture(scope="module")
def battle() -> BattleDefinition:
    return PokeredSource(Path(__file__).resolve().parents[1] / "external/pokered").build_battle()


def initial(battle: BattleDefinition, species: str = "CHARMANDER") -> BattleState:
    return create_rival_battle(battle, realize_starter(battle, species, battle.rival_dvs))


def test_source_data_and_all_pairings(battle: BattleDefinition) -> None:
    for species, rival, party, moves in (
        ("CHARMANDER", "SQUIRTLE", 1, ("SCRATCH", "GROWL")),
        ("SQUIRTLE", "BULBASAUR", 2, ("TACKLE", "TAIL_WHIP")),
        ("BULBASAUR", "CHARMANDER", 3, ("TACKLE", "GROWL")),
    ):
        state = initial(battle, species)
        assert state.rival.species == rival
        assert battle.rival_for(species).trainer_party == party
        assert tuple(move.constant for move in state.player.moves) == moves
        assert state.rival.dvs == DeterminantValues(attack_defense=0x98, speed_special=0x88)
        assert state.player.hp == state.player.stats.hp
        assert (
            battle.species_named(species).species.id
            != {"CHARMANDER": 4, "SQUIRTLE": 7, "BULBASAUR": 1}[species]
        )
    assert battle.move_named("TACKLE").accuracy == 242
    assert battle.move_named("SCRATCH").accuracy == 255
    assert {move.constant: (move.power, move.pp) for move in battle.moves} == {
        "TACKLE": (35, 35),
        "SCRATCH": (40, 35),
        "GROWL": (0, 40),
        "TAIL_WHIP": (0, 30),
        "STRUGGLE": (50, 10),
    }
    assert all(
        item.revision == "af519899719f0754965776faac0e836a3b906e6d" for item in battle.provenance
    )


@pytest.mark.parametrize(
    "species,base",
    [
        ("BULBASAUR", (45, 49, 49, 45, 65)),
        ("CHARMANDER", (39, 52, 43, 65, 50)),
        ("SQUIRTLE", (44, 48, 65, 43, 50)),
    ],
)
def test_all_dv_stats_against_independent_level_five_expectations(
    battle: BattleDefinition, species: str, base: tuple[int, ...]
) -> None:
    data = battle.species_named(species)
    for bits in range(65536):
        attack, defense, speed, special = ((bits >> shift) & 15 for shift in (12, 8, 4, 0))
        hp = 8 * (attack % 2) + 4 * (defense % 2) + 2 * (speed % 2) + special % 2
        stats = calculate_starter_stats(
            data,
            DeterminantValues(
                attack_defense=bits >> 8,
                speed_special=bits & 255,
            ),
        )
        assert tuple(stats.model_dump().values()) == (
            (base[0] + hp) // 10 + 15,
            (base[1] + attack) // 10 + 5,
            (base[2] + defense) // 10 + 5,
            (base[3] + speed) // 10 + 5,
            (base[4] + special) // 10 + 5,
        )


def test_player_random_draws_are_stored_reversed(battle: BattleDefinition) -> None:
    rng = Bytes(0x12, 0xAB)
    player = generate_player_starter(battle, "BULBASAUR", rng)
    assert player.dvs == DeterminantValues(attack_defense=0xAB, speed_special=0x12)
    assert rng.drawn == [0x12, 0xAB]
    assert create_rival_battle(battle, player).player == player
    with pytest.raises(ValueError, match="unsupported"):
        generate_player_starter(battle, "PIKACHU", Bytes())


def test_enemy_slot_boundaries_and_rejections(battle: BattleDefinition) -> None:
    rival = initial(battle).rival
    for byte in range(256):
        rng = Bytes(byte, 0)
        move = _rival_move(battle, rival, rng)
        assert move.constant == ("TAIL_WHIP" if 63 <= byte < 127 else "TACKLE")
        assert len(rng.drawn) == (1 if byte < 127 else 2)
    exhausted = rival.model_copy(
        update={"moves": tuple(m.model_copy(update={"pp": 0}) for m in rival.moves)}
    )
    assert _rival_move(battle, exhausted, Bytes(63)).constant == "TAIL_WHIP"


def test_exact_rng_order_and_pp_consumption_on_miss(battle: BattleDefinition) -> None:
    state = initial(battle)
    # Enemy slot; player critical; rejected damage then accepted damage; player
    # accuracy; discarded TrainerAI byte; rival critical/damage/accuracy.
    rng = Bytes(0, 255, 0, 255, 255, 42, 255, 255, 0)
    result = resolve_turn(battle, state, MoveCommand(slot=0), rng)
    assert rng.drawn == [0, 255, 0, 255, 255, 42, 255, 255, 0]
    assert [(e.type, e.side) for e in result.events] == [
        ("move", "player"),
        ("miss", "player"),
        ("move", "rival"),
        ("damage", "rival"),
    ]
    assert result.state.player.moves[0].pp == 34
    assert result.state.rival.moves == state.rival.moves
    assert state.player.moves[0].pp == 35


def test_critical_rotates_raw_byte_and_bypasses_debuffs(battle: BattleDefinition) -> None:
    state = initial(battle)
    actor = state.player.model_copy(update={"attack_stage": -6})
    target = state.rival.model_copy(update={"defense_stage": -6})
    for byte in range(256):
        damage, critical = _damage(
            battle, actor, target, battle.move_named("SCRATCH"), Bytes(byte, 255)
        )
        expected_critical = ((byte * 8) % 256 + byte // 32) < 32
        assert critical == expected_critical
        level = 10 if critical else 5
        attack = 11 if critical else 2
        defense = 12 if critical else 3
        assert damage == ((level * 2 // 5 + 2) * 40 * attack // defense) // 50 + 2


def test_all_damage_rotation_rejection_boundaries(battle: BattleDefinition) -> None:
    state = initial(battle)
    for byte in range(256):
        rng = Bytes(255, byte, 255)
        damage, critical = _damage(
            battle, state.player, state.rival, battle.move_named("SCRATCH"), rng
        )
        multiplier = byte // 2 + (byte % 2) * 128
        assert not critical
        assert damage == 4 * (multiplier if multiplier >= 217 else 255) // 255
        assert len(rng.drawn) == (2 if multiplier >= 217 else 3)


@pytest.mark.parametrize("byte,first", [(127, "player"), (128, "rival")])
def test_speed_tie_boundary(battle: BattleDefinition, byte: int, first: str) -> None:
    # Squirtle can tie the rival Bulbasaur at speed 10.
    player = realize_starter(
        battle, "SQUIRTLE", DeterminantValues(attack_defense=0, speed_special=0x70)
    )
    state = create_rival_battle(battle, player)
    assert state.player.stats.speed == state.rival.stats.speed == 10
    rng = Bytes(63, byte, *([255, 255, 0, 255, 255, 0, 0] * 2))
    result = resolve_turn(battle, state, MoveCommand(slot=1), rng)
    assert result.events[0].side == first


@pytest.mark.parametrize("byte,miss", [(63, True), (64, False), (255, False)])
def test_rival_stat_failure_precedes_accuracy(
    battle: BattleDefinition, byte: int, miss: bool
) -> None:
    rng = Bytes(63, 255, 255, 0, 123, byte, *([] if miss else [0]))
    result = resolve_turn(battle, initial(battle), MoveCommand(slot=0), rng)
    assert result.state.player.defense_stage == (0 if miss else -1)
    assert len(rng.drawn) == (6 if miss else 7)


@pytest.mark.parametrize("move_slot,accuracy", [(0, 242), (1, 255)])
def test_all_accuracy_bytes(battle: BattleDefinition, move_slot: int, accuracy: int) -> None:
    state = create_rival_battle(
        battle,
        realize_starter(battle, "SQUIRTLE", DeterminantValues(attack_defense=0, speed_special=0)),
    )
    for byte in range(256):
        prefix = [63, 17, 0]  # enemy move, GenericAI, enemy status failure
        player_rng = [255, 255, byte] if move_slot == 0 else [byte]
        result = resolve_turn(
            battle, state, MoveCommand(slot=move_slot), Bytes(*prefix, *player_rng)
        )
        assert any(e.type == "miss" and e.side == "player" for e in result.events) == (
            byte >= accuracy
        )


def test_negative_stat_ratios_and_minimum(battle: BattleDefinition) -> None:
    assert [_effective_stat(battle, 11, stage) for stage in range(0, -7, -1)] == [
        11,
        7,
        5,
        4,
        3,
        3,
        2,
    ]
    assert _effective_stat(battle, 1, -6) == 1
    state = initial(battle)
    for stage in range(0, -7, -1):
        staged = state.model_copy(
            update={"rival": state.rival.model_copy(update={"attack_stage": stage})}
        )
        result = resolve_turn(battle, staged, MoveCommand(slot=1), Bytes(63, 0, 0, 0))
        assert result.state.rival.attack_stage == max(-6, stage - 1)
        assert result.events[1].type == ("stat_failed" if stage == -6 else "stat_down")


def test_struggle_actual_damage_recoil_and_double_ko_party_exhaustion(
    battle: BattleDefinition,
) -> None:
    state = initial(battle)
    player = state.player.model_copy(
        update={
            "hp": 1,
            "moves": tuple(m.model_copy(update={"pp": 0}) for m in state.player.moves),
        }
    )
    rival = state.rival.model_copy(update={"hp": 1})
    result = resolve_turn(
        battle, BattleState(player=player, rival=rival), MoveCommand(), Bytes(0, 255, 255, 0)
    )
    assert result.state.outcome == "player_loss"
    assert result.state.player.hp == result.state.rival.hp == 0
    assert [(e.type, e.amount) for e in result.events] == [
        ("move", 0),
        ("damage", 1),
        ("recoil", 1),
        ("faint", 0),
    ]


def test_first_action_ko_skips_second_action_pp_and_rng(battle: BattleDefinition) -> None:
    state = initial(battle, "BULBASAUR")  # rival Charmander is faster.
    state = state.model_copy(update={"player": state.player.model_copy(update={"hp": 1})})
    rng = Bytes(0, 77, 255, 255, 0)
    result = resolve_turn(battle, state, MoveCommand(slot=0), rng)
    assert result.state.outcome == "player_loss"
    assert result.state.player.moves == state.player.moves
    assert len(rng.drawn) == 5
    assert all(e.side == "rival" for e in result.events[:-1])
    with pytest.raises(ValueError, match="ended"):
        resolve_turn(battle, result.state, MoveCommand(slot=0), Bytes())


def test_struggle_recoil_can_lose_without_target_fainting(battle: BattleDefinition) -> None:
    state = initial(battle)
    player = state.player.model_copy(
        update={
            "hp": 1,
            "moves": tuple(m.model_copy(update={"pp": 0}) for m in state.player.moves),
        }
    )
    result = resolve_turn(
        battle, state.model_copy(update={"player": player}), MoveCommand(), Bytes(0, 255, 255, 0)
    )
    assert result.state.outcome == "player_loss"
    assert result.state.rival.hp > 0
    assert [event.type for event in result.events] == ["move", "damage", "recoil", "faint"]


def test_granted_starter_oracle_detects_independent_stat_drift(battle: BattleDefinition) -> None:
    from tools.pokered_oracle.battle_stats import validate_granted_starter
    from tools.pokered_oracle.errors import OracleError

    # Independent canonical trainer-DV Charmander bytes: HP19 Atk11 Def10 Spd12 Spc10.
    memory = {
        "wPartyMon1Species": (176,),
        "wPartyMon1Level": (5,),
        "wPartyMon1DVs": (0x98, 0x88),
        "wPartyMon1Moves": (10, 45, 0, 0),
        "wPartyMon1PP": (35, 40, 0, 0),
        "wPartyMon1HPExp": (0,) * 10,
        "wPartyMon1HP": (0, 19),
        "wPartyMon1MaxHP": (0, 19),
        "wPartyMon1Attack": (0, 11),
        "wPartyMon1Defense": (0, 10),
        "wPartyMon1Speed": (0, 12),
        "wPartyMon1Special": (0, 10),
    }
    validate_granted_starter(battle, "CHARMANDER", lambda label, offset: memory[label][offset])
    memory["wPartyMon1Attack"] = (0, 12)
    with pytest.raises(OracleError, match="battle data differs"):
        validate_granted_starter(battle, "CHARMANDER", lambda label, offset: memory[label][offset])


def test_invalid_commands_and_states_consume_no_rng(battle: BattleDefinition) -> None:
    state = initial(battle)
    for command in (MoveCommand(), MoveCommand(slot=2)):
        with pytest.raises(ValueError):
            resolve_turn(battle, state, command, Bytes())
    exhausted = state.player.model_copy(
        update={"moves": tuple(m.model_copy(update={"pp": 0}) for m in state.player.moves)}
    )
    with pytest.raises(ValueError, match="Struggle"):
        resolve_turn(
            battle, state.model_copy(update={"player": exhausted}), MoveCommand(slot=0), Bytes()
        )
    with pytest.raises(ValueError, match="pairing"):
        resolve_turn(
            battle, state.model_copy(update={"rival": state.player}), MoveCommand(slot=0), Bytes()
        )
    with pytest.raises(ValidationError):
        MoveCommand(slot=True)
    with pytest.raises(ValidationError):
        state.player.hp = 1
    with pytest.raises(ValidationError):
        battle.provenance[0].file = "changed"


def test_battles_are_isolated_and_last_pp_is_usable(battle: BattleDefinition) -> None:
    first, other = initial(battle), initial(battle)
    first = first.model_copy(
        update={
            "player": first.player.model_copy(
                update={
                    "moves": tuple(
                        m.model_copy(update={"pp": 1 if i == 0 else 0})
                        for i, m in enumerate(first.player.moves)
                    )
                }
            )
        }
    )
    result = resolve_turn(battle, first, MoveCommand(slot=0), Bytes(63, 255, 255, 0, 0, 0))
    assert result.state.player.moves[0].pp == 0
    assert first.player.moves[0].pp == 1
    assert other.player.moves[0].pp == 35
    second = resolve_turn(battle, result.state, MoveCommand(), Bytes(63, 255, 255, 0, 0, 0))
    assert second.events[0].move == "STRUGGLE"
    assert second.state.turn == 2


def test_player_victory_ends_turn_before_rival_ai_draw(battle: BattleDefinition) -> None:
    state = initial(battle)
    state = state.model_copy(update={"rival": state.rival.model_copy(update={"hp": 1})})
    before = state.model_dump()
    rng = Bytes(0, 255, 255, 0)
    result = resolve_turn(battle, state, MoveCommand(slot=0), rng)
    assert result.state.outcome == "player_win"
    assert result.state.player.hp == state.player.hp
    assert result.state.rival.hp == 0
    assert result.state.player.moves[0].pp == 34
    assert result.state.turn == 1
    assert [(event.type, event.side) for event in result.events] == [
        ("move", "player"),
        ("damage", "player"),
        ("faint", "rival"),
    ]
    assert rng.drawn == [0, 255, 255, 0]
    assert state.model_dump() == before
    terminal_rng = Bytes()
    with pytest.raises(ValueError, match="ended"):
        resolve_turn(battle, result.state, MoveCommand(slot=0), terminal_rng)
    assert terminal_rng.drawn == []


@pytest.mark.parametrize("invalid", ["level", "stats", "pp", "empty_selected_slot"])
def test_invalid_player_rejected_before_randomness(battle: BattleDefinition, invalid: str) -> None:
    state = initial(battle)
    player = state.player
    if invalid == "level":
        player = player.model_copy(update={"level": 6})
    elif invalid == "stats":
        player = player.model_copy(
            update={"stats": player.stats.model_copy(update={"attack": player.stats.attack + 1})}
        )
    else:
        moves = list(player.moves)
        moves[0] = moves[0].model_copy(update={"pp": 36 if invalid == "pp" else 0})
        player = player.model_copy(update={"moves": tuple(moves)})
    state = state.model_copy(update={"player": player})
    before = state.model_dump()
    rng = Bytes()
    with pytest.raises(ValueError):
        resolve_turn(battle, state, MoveCommand(slot=0), rng)
    assert rng.drawn == []
    assert state.model_dump() == before


@pytest.mark.parametrize("byte", [-1, 256, True, 1.5])
def test_invalid_random_bytes_leave_input_state_intact(
    battle: BattleDefinition, byte: int | float
) -> None:
    state = initial(battle)
    before = state.model_dump()

    def invalid_rng() -> int:
        return byte  # type: ignore[return-value]

    with pytest.raises(ValueError, match="integer byte"):
        resolve_turn(battle, state, MoveCommand(slot=0), invalid_rng)
    assert state.model_dump() == before
    with pytest.raises(ValueError, match="integer byte"):
        generate_player_starter(battle, "CHARMANDER", invalid_rng)


def test_tail_whip_defense_stages_change_next_turn_damage(battle: BattleDefinition) -> None:
    state = initial(battle)
    # NPC Tail Whip succeeds, lowering the player's original defense 10 to 6.
    lowered = resolve_turn(battle, state, MoveCommand(slot=1), Bytes(63, 0, 42, 64, 0))
    assert lowered.state.player.defense_stage == -1
    damage, critical = _damage(
        battle,
        lowered.state.rival,
        lowered.state.player,
        battle.move_named("TACKLE"),
        Bytes(255, 255),
    )
    # Player Growl also reduced Squirtle's attack 10 to 6: floor(4*35*6/6/50)+2.
    assert (damage, critical) == (4, False)
    critical_damage, critical = _damage(
        battle,
        lowered.state.rival,
        lowered.state.player,
        battle.move_named("TACKLE"),
        Bytes(0, 255),
    )
    assert (critical_damage, critical) == (6, True)


def test_double_ko_state_cannot_claim_player_victory(battle: BattleDefinition) -> None:
    state = initial(battle)
    with pytest.raises(ValidationError, match="conscious player"):
        BattleState(
            player=state.player.model_copy(update={"hp": 0}),
            rival=state.rival.model_copy(update={"hp": 0}),
            outcome="player_win",
        )
