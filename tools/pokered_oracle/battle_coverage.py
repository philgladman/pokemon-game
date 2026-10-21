"""Optional live-ROM turn and outcome comparisons using ordinary joypad input."""

from __future__ import annotations

import json
from collections import deque
from dataclasses import asdict

from backend.app.engine.battle import resolve_turn
from backend.app.engine.pokemon import award_battle_experience
from backend.app.engine.text import resolve_text_pages
from backend.app.models.battle import (
    BattleDefinition,
    BattleEvent,
    BattlePokemon,
    BattleState,
    MoveCommand,
)
from backend.app.models.common import Direction, Position
from backend.app.source.pokered.source import PINNED_REVISION

from .artifacts import OraclePaths
from .battle_observer import BattleObserver
from .errors import OracleError
from .gameplay import (
    InteractionContract,
    RuntimeGameplayDriver,
    SourceGameplayDriver,
    visible_actor,
)
from .runtime import RuntimeAdapter


class ObservedRandom:
    """Grant source-observed DVs in AddPartyMon order, then replay decision bytes."""

    def __init__(self, observer: BattleObserver) -> None:
        self.observer = observer
        self.values: deque[int] | None = None
        self._grant_index = 0

    def __deepcopy__(self, memo: dict[int, object]) -> ObservedRandom:
        # Emulator handles cannot be copied. Every replay explicitly replaces the
        # decision buffer, and every starter grant consumes exactly two bytes.
        return self

    def __call__(self) -> int:
        if self.values is not None:
            if not self.values:
                raise OracleError("runtime requested an unobserved battle random byte")
            return self.values.popleft()
        offset = 1 if self._grant_index % 2 == 0 else 0
        self._grant_index += 1
        return self.observer.read("wPartyMon1DVs", offset)

    def replay(self, values: list[int]) -> None:
        self.values = deque(values)

    def exhausted(self) -> None:
        if self.values:
            raise OracleError(f"runtime left {len(self.values)} observed battle bytes unused")


def pokemon_state(
    definition: BattleDefinition, pokemon: BattlePokemon, money: int
) -> dict[str, object]:
    return {
        "species_id": definition.species_named(pokemon.species).species.id,
        "level": pokemon.level,
        "dvs": [pokemon.dvs.attack_defense, pokemon.dvs.speed_special],
        "hp": pokemon.hp,
        "stats": pokemon.stats.model_dump(),
        "moves": [
            *(definition.move_named(move.constant).id for move in pokemon.moves),
            *([0] * (4 - len(pokemon.moves))),
        ],
        "pp": [*(move.pp for move in pokemon.moves), *([0] * (4 - len(pokemon.moves)))],
        "experience": pokemon.experience,
        "stat_experience": list(pokemon.stat_experience.model_dump().values()),
        "status": 0,
        "money": money,
    }


def combat_state(definition: BattleDefinition, state: BattleState) -> dict[str, object]:
    result: dict[str, object] = {
        "player_hp": state.player.hp,
        "rival_hp": state.rival.hp,
        "player_pp": [
            *(move.pp for move in state.player.moves),
            *([0] * (4 - len(state.player.moves))),
        ],
    }
    for side in ("player", "rival"):
        pokemon = getattr(state, side)
        for name in ("attack", "defense"):
            stage = getattr(pokemon, f"{name}_stage")
            numerator, denominator = definition.stat_ratios[stage + 6]
            result[f"{side}_{name}_stage"] = stage
            result[f"{side}_{name}"] = max(
                1, getattr(pokemon.stats, name) * numerator // denominator
            )
    return result


class BattleCoverage:
    def __init__(
        self,
        source: SourceGameplayDriver,
        runtime: RuntimeAdapter,
        definition: BattleDefinition,
        observer: BattleObserver,
        rng: ObservedRandom,
        paths: OraclePaths,
    ) -> None:
        self.source = source
        self.runtime = runtime
        self.driver = RuntimeGameplayDriver(runtime, source.world)
        self.definition = definition
        self.observer = observer
        self.rng = rng
        self.paths = paths
        self.source_records: list[dict[str, object]] = []
        self.runtime_records: list[dict[str, object]] = []
        self.completed: list[str] = []

    def _compare(self, label: str, expected: object, observed: object) -> None:
        self.runtime_records.append({"checkpoint": label, "state": expected})
        self.source_records.append({"checkpoint": label, "state": observed})
        self.write_traces()
        if expected != observed:
            raise OracleError(f"battle mismatch at {label}: expected={expected}; ROM={observed}")

    def write_traces(self) -> None:
        for origin, records in (
            ("runtime", self.runtime_records),
            ("pokered", self.source_records),
        ):
            path = self.paths.trace_path("phase-3b-live-battle", origin)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "scenario": "phase-3b-live-battle",
                        "origin": origin,
                        "source_revision": PINNED_REVISION,
                        "completed": self.completed,
                        "checkpoints": records,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

    def run_starter(self, species: str) -> None:
        self.source.save_checkpoint("battle-granted")
        self.runtime.save_checkpoint("battle-granted")
        try:
            for desired in ("player_win", "player_loss"):
                for attempt in range(12):
                    self.observer.active = False
                    self.source.load_checkpoint("battle-granted")
                    self.runtime.load_checkpoint("battle-granted")
                    self.observer.reset()
                    self.observer.preheal = None
                    self.rng.values = None
                    # Ordinary idle frames alter the source's frame-clock RNG.
                    self.source.emulator.tick(attempt * 17)
                    outcome = self._battle(species, desired, attempt)
                    if outcome == desired:
                        self.completed.append(f"{species.lower()}/{desired}")
                        print(f"oracle battle: {species} {desired} matches live ROM", flush=True)
                        break
                else:
                    raise OracleError(f"could not obtain live {species} {desired} in 12 attempts")
        except OracleError as error:
            self.source_records.append(
                {
                    "failure": str(error),
                    "draws": [asdict(draw) for draw in self.observer.draws],
                    "actions": [asdict(action) for action in self.observer.actions],
                    "overworld": asdict(self.source.capture("battle-failure")),
                }
            )
            raise
        finally:
            self.observer.active = False
            self.source.load_checkpoint("battle-granted")
            self.runtime.load_checkpoint("battle-granted")
            self.rng.values = None
            self.write_traces()

    def _ack(self) -> None:
        battle = self.runtime.snapshot().battle
        if battle is None or battle.batch is None:
            raise OracleError("runtime battle has no pending presentation batch")
        result = self.runtime.session.acknowledge_battle(battle.id, battle.batch.id)
        if result.action == "blocked":
            raise OracleError(f"runtime battle acknowledgement failed: {result.reason}")

    def _battle(self, species: str, desired: str, attempt: int) -> str:
        emulator = self.source.emulator
        prefix = f"{species.lower()}/{desired}/attempt-{attempt}"
        for driver in (self.source, self.driver):
            driver.walk_to(Position(x=5, y=5))
            driver.walk_tiles(Direction.SOUTH)
        self.driver.advance_until("battle-ready", lambda state: state.control_mode == "battle")
        emulator.press_until_symbol("a", "DisplayBattleMenu", max_frames=18_000)
        emulator.press_until_symbol("a", "DisplayBattleMenu.handleBattleMenuInput", max_frames=1800)
        battle = self.runtime.session._battle
        if battle is None:
            raise OracleError("runtime did not start the rival battle")
        self._compare(
            prefix + "/initial",
            combat_state(self.definition, battle.state),
            self.observer.combat_state(),
        )
        self._ack()
        self.observer.active = True
        for turn in range(60):
            battle = self.runtime.session._battle
            if battle is None:
                raise OracleError("runtime battle disappeared before its terminal acknowledgement")
            state = battle.state
            slot = 0 if desired == "player_win" else 1
            if not state.player.moves[slot].pp:
                slot = next((i for i, move in enumerate(state.player.moves) if move.pp), 0)
            self.observer.reset()
            emulator.press_until_symbol("a", "MoveSelectionMenu.menuset", max_frames=1800)
            for _ in range(8):
                if self.observer.read("wCurrentMenuItem") == slot + 1:
                    break
                emulator.press("down", 2, 2)
            else:
                raise OracleError("source move menu did not select requested move slot")
            emulator.press_until_symbol("a", "SelectEnemyMove", max_frames=1800)
            deadline = emulator.port.frame + 18_000
            while self.observer.boundary is None and emulator.port.frame < deadline:
                emulator.press("a", 1, 1)
            if self.observer.boundary is None:
                raise OracleError(f"source battle turn {turn} exceeded 18000 frames")
            values = [draw.value for draw in self.observer.draws]
            self.source_records.append(
                {
                    "checkpoint": prefix + f"/turn-{turn}/rng",
                    "draws": [asdict(draw) for draw in self.observer.draws],
                }
            )
            iterator = iter(values)
            try:
                resolved = resolve_turn(
                    self.definition, state, MoveCommand(slot=slot), iterator.__next__
                )
            except StopIteration as error:
                raise OracleError(
                    f"{prefix}/turn-{turn}: resolver exhausted observed RNG"
                ) from error
            if list(iterator):
                raise OracleError(f"{prefix}/turn-{turn}: resolver left observed RNG unused")
            self._actions(prefix + f"/turn-{turn}", state, resolved.events, slot)
            self._compare(
                prefix + f"/turn-{turn}/state",
                combat_state(self.definition, resolved.state),
                self.observer.combat_state(),
            )
            self._compare(
                prefix + f"/turn-{turn}/outcome",
                resolved.state.outcome,
                "ongoing" if self.observer.boundary == "turn" else self.observer.boundary,
            )
            self.rng.replay(values)
            snapshot = self.runtime.snapshot().battle
            assert snapshot is not None and snapshot.action_token is not None
            action = self.runtime.session.battle_action(snapshot.id, snapshot.action_token, slot)
            if action.action == "blocked":
                raise OracleError(f"runtime rejected source move: {action.reason}")
            self.rng.exhausted()
            if battle.state != award_battle_experience(self.definition, resolved.state):
                raise OracleError(f"{prefix}/turn-{turn}: session differs from pure resolver")
            if resolved.state.outcome != "ongoing":
                self._finish(prefix, resolved.state)
                return resolved.state.outcome
            self._ack()
        raise OracleError(f"{prefix}: battle exceeded 60 turns")

    def _actions(
        self, prefix: str, before: BattleState, events: tuple[BattleEvent, ...], slot: int
    ) -> None:
        state = before
        groups: list[list[BattleEvent]] = []
        for event in events:
            if event.type == "move":
                groups.append([])
            groups[-1].append(event)
        if len(groups) != len(self.observer.actions):
            raise OracleError(f"{prefix}: source and runtime action counts differ")
        for index, (group, observed) in enumerate(zip(groups, self.observer.actions, strict=True)):
            first = group[0]
            actor = getattr(state, first.side)
            other = "rival" if first.side == "player" else "player"
            target = getattr(state, other)
            if first.side == "player":
                actor = actor.model_copy(
                    update={
                        "moves": tuple(
                            move.model_copy(update={"pp": move.pp - 1}) if i == slot else move
                            for i, move in enumerate(actor.moves)
                        )
                    }
                )
            for event in group[1:]:
                if event.type == "damage":
                    target = target.model_copy(update={"hp": target.hp - event.amount})
                elif event.type == "recoil":
                    actor = actor.model_copy(update={"hp": actor.hp - event.amount})
                elif event.type == "stat_down":
                    effect = self.definition.move_named(event.move).effect
                    name = "attack_stage" if effect == "attack_down" else "defense_stage"
                    target = target.model_copy(update={name: getattr(target, name) - 1})
            state = state.model_copy(update={first.side: actor, other: target})
            expected = {
                "side": first.side,
                "move": self.definition.move_named(first.move).id,
                "after": combat_state(self.definition, state),
                "missed": any(event.type == "miss" for event in group),
                "failed": any(event.type == "stat_failed" for event in group),
            }
            actual = asdict(observed)
            if any(event.type == "damage" for event in group):
                expected["critical"] = any(event.critical for event in group)
            else:
                actual.pop("critical")
            self._compare(prefix + f"/move-{index}", expected, actual)

    def _finish(self, prefix: str, terminal: BattleState) -> None:
        emulator = self.source.emulator
        deadline = emulator.port.frame + 18_000
        while self.observer.preheal is None and emulator.port.frame < deadline:
            emulator.press("a", 1, 1)
        if self.observer.preheal is None:
            raise OracleError(f"{prefix}: source did not return to the lab before healing")
        completed = award_battle_experience(self.definition, terminal).player
        money = self.definition.starting_money
        if terminal.outcome == "player_win":
            money += self.definition.trainer_base_money * terminal.rival.level
        self._compare(
            prefix + "/preheal",
            pokemon_state(self.definition, completed, money),
            self.observer.preheal,
        )
        self._ack()
        farewell = InteractionContract("rival_farewell", "TEXT_OAKSLAB_RIVAL_SMELL_YOU_LATER")
        self.source.expect_dialog(farewell)
        self.driver.advance_until("healed-farewell", lambda state: state.control_mode == "dialog")
        pokemon = (
            self.runtime.session._story.player_pokemon if self.runtime.session._story else None
        )
        if pokemon is None:
            raise OracleError("runtime lost authoritative party after battle")
        self._compare(
            prefix + "/healed",
            pokemon_state(self.definition, pokemon, self.runtime.snapshot().money),
            self.observer.party_state(),
        )
        dialog = self.runtime.snapshot().dialog
        self._compare(prefix + "/farewell", dialog.interaction_id if dialog else None, farewell.id)
        self._world(prefix + "/healed-farewell", free=False)
        paths: list[object] = []
        for driver in (self.source, self.driver):
            driver.begin_motion(("OAKSLAB_RIVAL",))
            driver.dismiss_dialog()
            driver.advance_until(
                "rival-departed",
                lambda state: (
                    visible_actor(state, "OAKSLAB_RIVAL") is None
                    and "EVENT_BATTLED_RIVAL_IN_OAKS_LAB" in (state.flags or ())
                ),
            )
            paths.append([asdict(track) for track in driver.finish_motion()])
        self._compare(prefix + "/departure-path", paths[1], paths[0])
        self._world(prefix + "/departure")
        self._postbattle_text(
            prefix,
            "OAKSLAB_OAK1",
            "oak_raise",
            "TEXT_OAKSLAB_OAK1",
            "OaksLabOak1Text.RaiseYourYoungPokemonText",
        )
        remaining = next(
            actor.id
            for actor in self.source.capture("remaining-ball").actors or ()
            if actor.visible and actor.id.endswith("POKE_BALL")
        )
        self._postbattle_text(
            prefix, remaining, "last_mon", f"TEXT_{remaining}", "OaksLabLastMonText"
        )
        self.observer.active = False
        for driver in (self.source, self.driver):
            driver.walk_to(Position(x=4, y=10))
            for _ in range(3):
                if driver.capture("lab-exit").map_id != "OAKS_LAB":
                    break
                driver.walk_tiles(Direction.SOUTH)
            else:
                raise OracleError(f"{prefix}: could not exit the lab")
            driver.walk_tiles(Direction.NORTH)
        self._world(prefix + "/reentry")
        if self.runtime.snapshot().battle is not None or self.observer.read("wIsInBattle"):
            raise OracleError(f"{prefix}: battle retriggered on lab reentry")

    def _postbattle_text(
        self,
        prefix: str,
        actor: str,
        text_id: str,
        constant: str,
        source_label: str,
    ) -> None:
        contract = InteractionContract("oak_raise" if text_id == "oak_raise" else actor, constant)
        baseline = len(self.observer.printed_texts)
        self.source.interact_actor(actor, contract)
        self.source.emulator.wait_until(
            source_label,
            lambda _: len(self.observer.printed_texts) > baseline,
            max_frames=1200,
        )
        self._compare(
            prefix + "/" + text_id + "/source-branch", source_label, self.observer.printed_texts[-1]
        )
        self.driver.interact_actor(actor, contract)
        story = self.runtime.session._story
        dialog = self.runtime.snapshot().dialog
        if story is None or dialog is None:
            raise OracleError(f"{prefix}: missing runtime {text_id} interaction")
        expected = resolve_text_pages(
            list(story.definition.texts[text_id].pages), story.world.text_variables
        )
        self._compare(prefix + "/" + text_id + "/pages", expected, dialog.pages)
        self.source.dismiss_dialog()
        self.driver.dismiss_dialog()

    def _world(self, label: str, *, free: bool = True) -> None:
        def state(driver: SourceGameplayDriver | RuntimeGameplayDriver) -> dict[str, object]:
            capture = driver.capture(label)
            return {
                "map": capture.map_id,
                "x": capture.player_x,
                "y": capture.player_y,
                "facing": capture.facing,
                "rival": visible_actor(capture, "OAKSLAB_RIVAL"),
                "flags": capture.flags,
                "oak1": visible_actor(capture, "OAKSLAB_OAK1"),
                "oak2": visible_actor(capture, "OAKSLAB_OAK2"),
                # Poké Balls use nondirectional graphics; their sprite facing
                # scratch byte is incidental, unlike Oak/rival/player facing.
                "balls": [
                    (ball[:2] if ball is not None else None)
                    for name in ("CHARMANDER", "SQUIRTLE", "BULBASAUR")
                    for ball in [visible_actor(capture, f"OAKSLAB_{name}_POKE_BALL")]
                ],
                "control_mode": capture.control_mode,
            }

        self._compare(label, state(self.driver), state(self.source))
        if free and (
            self.observer.read("wJoyIgnore") or self.runtime.snapshot().control_mode != "free"
        ):
            raise OracleError(f"{label}: overworld input was not restored")
