"""Translate the pinned Red lab battle's supported turn paths.

The injected stream represents calls to Random/BattleRandom within battle
decisions, including TrainerAI's discarded byte. It is not a frame-clock PRNG:
UI, audio and overworld random calls are outside this engine.
"""

from __future__ import annotations

from backend.app.models.battle import (
    BattleDefinition,
    BattleEvent,
    BattleOutcome,
    BattlePokemon,
    BattleState,
    MoveCommand,
    MoveDefinition,
    Side,
    TurnResult,
)

from .pokemon import ByteRng, calculate_starter_stats, random_byte


def _validate_state(definition: BattleDefinition, state: BattleState) -> None:
    mapping = definition.rival_for(state.player.species)
    if state.rival.species != mapping.rival_species or state.rival.dvs != definition.rival_dvs:
        raise ValueError("unsupported first-rival-battle pairing or rival DVs")
    for pokemon in (state.player, state.rival):
        if pokemon.level != 5:
            raise ValueError("only level-five starter battles are supported")
        species = definition.species_named(pokemon.species)
        if pokemon.stats != calculate_starter_stats(species, pokemon.dvs):
            raise ValueError("starter stats must match level-five DVs and zero stat experience")
        if tuple(move.constant for move in pokemon.moves) != species.starting_moves:
            raise ValueError("unsupported starter move slots")
        if any(move.pp > definition.move_named(move.constant).pp for move in pokemon.moves):
            raise ValueError("starter PP exceeds its source maximum")


def _player_move(
    definition: BattleDefinition, player: BattlePokemon, command: MoveCommand
) -> MoveDefinition:
    if not any(move.pp for move in player.moves):
        if command.slot is not None:
            raise ValueError("exhausted moves require Struggle (slot=None)")
        return definition.move_named("STRUGGLE")
    if command.slot is None or command.slot >= len(player.moves):
        raise ValueError("select an existing move slot")
    selected = player.moves[command.slot]
    if not selected.pp:
        raise ValueError("selected move has no PP")
    return definition.move_named(selected.constant)


def _rival_move(definition: BattleDefinition, rival: BattlePokemon, rng: ByteRng) -> MoveDefinition:
    # SelectEnemyMove uses percent=*255//100; these are 63,127,190.
    # Empty slots are rejected and sampled again. NPC PP is never consulted.
    while True:
        byte = random_byte(rng)
        slot = 0 if byte < 63 else 1 if byte < 127 else 2 if byte < 190 else 3
        if slot < len(rival.moves):
            return definition.move_named(rival.moves[slot].constant)


def _effective_stat(definition: BattleDefinition, original: int, stage: int) -> int:
    numerator, denominator = definition.stat_ratios[stage + 6]
    return max(1, original * numerator // denominator)


def _damage(
    definition: BattleDefinition,
    actor: BattlePokemon,
    target: BattlePokemon,
    move: MoveDefinition,
    rng: ByteRng,
) -> tuple[int, bool]:
    # CriticalHitTest rotates the byte three times, then compares base speed/2.
    byte = random_byte(rng)
    rotated = ((byte << 3) | (byte >> 5)) & 255
    critical = rotated < definition.species_named(actor.species).base_stats.speed // 2
    attack = actor.stats.attack
    defense = target.stats.defense
    if not critical:
        attack = _effective_stat(definition, attack, actor.attack_stage)
        defense = _effective_stat(definition, defense, target.defense_stage)
    # All supported moves are physical Normal, and all supported targets are
    # neutral non-Normal starters: AdjustDamageForMoveType leaves this unchanged.
    level = actor.level * (2 if critical else 1)
    damage = ((2 * level // 5 + 2) * move.power * attack // defense) // 50 + 2
    if damage > 1:
        while True:
            byte = random_byte(rng)
            multiplier = ((byte >> 1) | (byte << 7)) & 255
            if multiplier >= 217:
                damage = damage * multiplier // 255
                break
    return damage, critical


def _act(
    definition: BattleDefinition,
    actor: BattlePokemon,
    target: BattlePokemon,
    side: Side,
    move: MoveDefinition,
    slot: int | None,
    rng: ByteRng,
) -> tuple[BattlePokemon, BattlePokemon, tuple[BattleEvent, ...]]:
    events = [BattleEvent(type="move", side=side, move=move.constant)]
    if side == "rival":
        random_byte(rng)  # TrainerAI calls Random even for GenericAI's no-op.
    elif slot is not None:
        moves = tuple(
            item.model_copy(update={"pp": item.pp - 1}) if index == slot else item
            for index, item in enumerate(actor.moves)
        )
        actor = actor.model_copy(update={"moves": moves})
    if move.effect in {"attack_down", "defense_down"}:
        # StatModifierDownEffect performs this additional NPC failure BEFORE accuracy.
        if side == "rival" and random_byte(rng) < 64:
            events.append(BattleEvent(type="miss", side=side, move=move.constant))
            return actor, target, tuple(events)
        if random_byte(rng) >= move.accuracy:
            events.append(BattleEvent(type="miss", side=side, move=move.constant))
            return actor, target, tuple(events)
        field = "attack_stage" if move.effect == "attack_down" else "defense_stage"
        stage = target.attack_stage if field == "attack_stage" else target.defense_stage
        original = target.stats.attack if field == "attack_stage" else target.stats.defense
        if stage == -6 or _effective_stat(definition, original, stage) == 1:
            events.append(BattleEvent(type="stat_failed", side=side, move=move.constant))
        else:
            target = target.model_copy(update={field: stage - 1})
            events.append(BattleEvent(type="stat_down", side=side, move=move.constant, amount=1))
        return actor, target, tuple(events)

    damage, critical = _damage(definition, actor, target, move, rng)
    # Execute*Move runs damage (including rejection draws) BEFORE MoveHitTest.
    if random_byte(rng) >= move.accuracy:
        events.append(BattleEvent(type="miss", side=side, move=move.constant))
        return actor, target, tuple(events)
    inflicted = min(damage, target.hp)
    target = target.model_copy(update={"hp": target.hp - inflicted})
    events.append(
        BattleEvent(
            type="damage",
            side=side,
            move=move.constant,
            amount=inflicted,
            critical=critical,
        )
    )
    if move.effect == "recoil":
        recoil = min(actor.hp, max(1, inflicted // 2))
        actor = actor.model_copy(update={"hp": actor.hp - recoil})
        events.append(BattleEvent(type="recoil", side=side, move=move.constant, amount=recoil))
    other: Side = "rival" if side == "player" else "player"
    if not target.hp:
        events.append(BattleEvent(type="faint", side=other, move=move.constant))
    if not actor.hp:
        events.append(BattleEvent(type="faint", side=side, move=move.constant))
    if not actor.hp and not target.hp:
        # FaintEnemyPokemon returns before EnemyMonFaintedText when the only
        # party member has fainted; RemoveFaintedPlayerMon supplies its text.
        events = [event for event in events if event.type != "faint" or event.side == "player"]
    return actor, target, tuple(events)


def resolve_turn(
    definition: BattleDefinition, state: BattleState, command: MoveCommand, rng: ByteRng
) -> TurnResult:
    """Resolve one complete turn without mutating input state or source definitions."""
    if state.outcome != "ongoing":
        raise ValueError("battle has already ended")
    _validate_state(definition, state)
    selected = _player_move(definition, state.player, command)
    rival_move = _rival_move(definition, state.rival, rng)
    player_first = state.player.stats.speed > state.rival.stats.speed
    if state.player.stats.speed == state.rival.stats.speed:
        player_first = random_byte(rng) < 128
    order: tuple[Side, Side] = ("player", "rival") if player_first else ("rival", "player")
    player, rival = state.player, state.rival
    events: list[BattleEvent] = []
    outcome: BattleOutcome = "ongoing"
    for side in order:
        actor, target = (player, rival) if side == "player" else (rival, player)
        move = selected if side == "player" else rival_move
        actor, target, action_events = _act(
            definition,
            actor,
            target,
            side,
            move,
            command.slot if side == "player" else None,
            rng,
        )
        player, rival = (actor, target) if side == "player" else (target, actor)
        events.extend(action_events)
        # HandleEnemyMonFainted checks AnyPartyAlive before TrainerBattleVictory.
        # With one Pokémon each, player recoil exhaustion loses even on a double KO.
        if not player.hp:
            outcome = "player_loss"
            break
        if not rival.hp:
            outcome = "player_win"
            break
    return TurnResult(
        state=BattleState(player=player, rival=rival, turn=state.turn + 1, outcome=outcome),
        events=tuple(events),
    )
