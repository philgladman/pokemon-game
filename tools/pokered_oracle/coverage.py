from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path

from backend.app.models.common import Direction, Position
from backend.app.models.story import StoryDefinition

from .errors import OracleError
from .gameplay import (
    GameplayDriver,
    InteractionContract,
    MovementTiming,
    project_state,
    visible_actor,
)
from .trace import SemanticState, SemanticTrace, TraceRecorder, require_matching_traces

SCENARIO_ID = "phase-3a-live-coverage"
STORY_FLAGS = frozenset(
    {
        "EVENT_OAK_APPEARED_IN_PALLET",
        "EVENT_FOLLOWED_OAK_INTO_LAB",
        "EVENT_FOLLOWED_OAK_INTO_LAB_2",
        "EVENT_OAK_ASKED_TO_CHOOSE_MON",
        "EVENT_GOT_STARTER",
        "EVENT_BATTLED_RIVAL_IN_OAKS_LAB",
    }
)


@dataclass(frozen=True)
class CoverageResult:
    runtime: SemanticTrace
    source: SemanticTrace
    scenarios: tuple[str, ...]


class Phase3ACoverage:
    """Drive source and Python through the same Phase 3A semantic operations."""

    def __init__(
        self,
        source: GameplayDriver,
        runtime: GameplayDriver,
        story: StoryDefinition,
        source_revision: str,
        on_starter_granted: Callable[[str], None] | None = None,
        on_starter_complete: Callable[[str], None] | None = None,
    ) -> None:
        self.source = source
        self.runtime = runtime
        self.story = story
        self._source_trace = TraceRecorder(SCENARIO_ID, "pokered", source_revision)
        self._runtime_trace = TraceRecorder(SCENARIO_ID, "runtime", source_revision)
        self._scenarios: list[str] = []
        self._on_starter_granted = on_starter_granted
        self._on_starter_complete = on_starter_complete

    def run(self) -> CoverageResult:
        self.source.save_checkpoint("new-game")
        self.runtime.save_checkpoint("new-game")
        self._movement()
        self._house()
        self._interactions()
        self.source.save_checkpoint("pallet-exploration")
        self.runtime.save_checkpoint("pallet-exploration")
        self._oak_branch(10, save_lab=True)
        self._oak_branch(11, save_lab=False)
        self._starters()
        source_trace = self._source_trace.finish()
        runtime_trace = self._runtime_trace.finish()
        require_matching_traces(runtime_trace, source_trace)
        return CoverageResult(runtime_trace, source_trace, tuple(self._scenarios))

    def _movement(self) -> None:
        tile_frames, resample_frames = frontend_movement_frames(
            Path(__file__).resolve().parents[2] / "frontend/src"
        )
        source_turn = self.source.turn(Direction.WEST)
        self.runtime.turn(Direction.WEST)
        _bounded("changed-direction tap", source_turn, 1, 3)
        self._record("movement-turn-only", ("map_id", "player_x", "player_y", "facing"))

        source_west = self.source.walk_tiles(Direction.WEST)
        self.runtime.walk_tiles(Direction.WEST)
        _validate_tile_timing("fresh same-facing press", source_west, 1, tile_frames)
        self._record("movement-fresh-same-facing", ("map_id", "player_x", "player_y", "facing"))

        source_east = self.source.walk_tiles(Direction.EAST, 2)
        self.runtime.walk_tiles(Direction.EAST, 2)
        _validate_tile_timing("held changed direction", source_east, 2, tile_frames)
        if source_east.turn_to_walk_frames is None:
            raise OracleError("held changed direction did not expose a turn-to-walk resample")
        _bounded(
            "held-input turn resample",
            source_east.turn_to_walk_frames,
            resample_frames - 1,
            resample_frames + 1,
        )
        self._record(
            "movement-held-changed-direction", ("map_id", "player_x", "player_y", "facing")
        )

        source_fresh = self.source.walk_tiles(Direction.EAST)
        self.runtime.walk_tiles(Direction.EAST)
        _validate_tile_timing("fresh same-facing press", source_fresh, 1, tile_frames)
        self._record("movement-held-input", ("map_id", "player_x", "player_y", "facing"))
        self._scenarios.append("movement/held-input")

    def _house(self) -> None:
        self._apply(lambda driver: driver.walk_to(Position(x=7, y=1)))
        self._record("house-stairs", ("map_id", "player_x", "player_y", "facing"))

        self._interaction(
            "house-mom",
            InteractionContract("mom_wake", "TEXT_REDSHOUSE1F_MOM"),
            actor_id="REDSHOUSE1F_MOM",
        )
        self._interaction(
            "house-tv",
            InteractionContract("tv", "TEXT_REDSHOUSE1F_TV"),
            target=Position(x=3, y=1),
        )

        self._apply(lambda driver: driver.save_checkpoint("house-exits"))
        for column in (2, 3):
            self._house_exit(column)
        self._apply(lambda driver: driver.exit_reds_house())
        self._scenarios.append("house-transitions")

    def _house_exit(self, column: int) -> None:
        self._apply(lambda driver: driver.load_checkpoint("house-exits"))
        self._apply(lambda driver: driver.walk_to(Position(x=column, y=6)))
        self._record(f"house-{column}-before-exit", ("map_id", "player_x", "player_y"))
        self._track(
            f"house-{column}-exit-path", ("player",), lambda driver: driver.exit_reds_house(column)
        )
        self._record(f"house-{column}-exit", ("map_id", "player_x", "player_y", "facing"))
        self._track(
            f"house-{column}-reentry-path",
            ("player",),
            lambda driver: driver.walk_tiles(Direction.NORTH),
        )
        self._record(f"house-{column}-reentry", ("map_id", "player_x", "player_y", "facing"))

    def _interactions(self) -> None:
        for label, target, reference in (
            (
                "lab-sign",
                Position(x=13, y=13),
                "TEXT_PALLETTOWN_OAKSLAB_SIGN",
            ),
            ("town-sign", Position(x=7, y=9), "TEXT_PALLETTOWN_SIGN"),
            (
                "player-house-sign",
                Position(x=3, y=5),
                "TEXT_PALLETTOWN_PLAYERSHOUSE_SIGN",
            ),
            (
                "rival-house-sign",
                Position(x=11, y=5),
                "TEXT_PALLETTOWN_RIVALSHOUSE_SIGN",
            ),
        ):
            self._interaction(label, InteractionContract(reference, reference), target=target)
        self._interaction(
            "girl",
            InteractionContract("PALLETTOWN_GIRL", "TEXT_PALLETTOWN_GIRL"),
            actor_id="PALLETTOWN_GIRL",
        )
        self._interaction(
            "fisher",
            InteractionContract("PALLETTOWN_FISHER", "TEXT_PALLETTOWN_FISHER"),
            actor_id="PALLETTOWN_FISHER",
        )
        self._scenarios.append("signs/NPCs")

    def _oak_branch(self, column: int, *, save_lab: bool) -> None:
        self.source.load_checkpoint("pallet-exploration")
        self.runtime.load_checkpoint("pallet-exploration")
        self._apply(lambda driver: driver.walk_to(Position(x=10, y=2)))
        if column == 11:
            self._apply(lambda driver: driver.walk_tiles(Direction.EAST))
        self._apply(lambda driver: driver.walk_tiles(Direction.NORTH))
        hey_wait = InteractionContract("oak_hey_wait", "TEXT_PALLETTOWN_OAK")
        self.source.expect_dialog(hey_wait)
        self.runtime.expect_dialog(hey_wait)
        self._record(
            f"oak-{column}-intercept",
            ("map_id", "player_x", "player_y", "facing", "flags"),
        )
        unsafe = InteractionContract("oak_unsafe", "TEXT_PALLETTOWN_OAK")

        def approach(driver: GameplayDriver) -> None:
            driver.dismiss_dialog()
            driver.expect_dialog(unsafe)

        self._track(f"oak-{column}-approach", ("player", "PALLETTOWN_OAK"), approach)
        self._apply(lambda driver: driver.dismiss_dialog())
        self._both_advance(
            f"oak-{column}-common-start",
            lambda state: (
                state.map_id == "PALLET_TOWN"
                and (state.player_x, state.player_y) == (10, 1)
                and (visible_actor(state, "PALLETTOWN_OAK") or ())[:2] == (10, 2)
            ),
            actor_ids=("player", "PALLETTOWN_OAK"),
        )
        self._record(
            f"oak-{column}-common-start",
            ("map_id", "player_x", "player_y", "facing"),
            actor_ids=("PALLETTOWN_OAK",),
        )
        self._both_advance(
            f"oak-{column}-lab-arrival",
            lambda state: (
                state.map_id == "OAKS_LAB" and (state.player_x, state.player_y) == (5, 11)
            ),
            actor_ids=("player", "PALLETTOWN_OAK"),
        )
        self._record(
            f"oak-{column}-lab-arrival",
            ("map_id", "player_x", "player_y", "facing"),
        )
        self._both_advance(
            f"oak-{column}-lab-ready",
            lambda state: (
                state.map_id == "OAKS_LAB"
                and (state.player_x, state.player_y) == (5, 3)
                and "EVENT_OAK_ASKED_TO_CHOOSE_MON" in (state.flags or ())
            ),
            actor_ids=("player", "OAKSLAB_OAK1", "OAKSLAB_OAK2", "OAKSLAB_RIVAL"),
        )
        self._record(
            f"oak-{column}-lab-ready",
            ("map_id", "player_x", "player_y", "facing", "flags"),
            actor_ids=("OAKSLAB_OAK1", "OAKSLAB_OAK2", "OAKSLAB_RIVAL"),
            actor_facing=True,
        )
        if save_lab:
            self.source.save_checkpoint("lab-choice")
            self.runtime.save_checkpoint("lab-choice")
        self._scenarios.append(f"oak-column-{column}/lab-entry")

    def _starters(self) -> None:
        for ball, starter in self.story.starters.items():
            species = starter.species.constant
            self.source.load_checkpoint("lab-choice")
            self.runtime.load_checkpoint("lab-choice")
            target = self._actor_position(self.runtime.capture("starter-ball"), ball)
            contract = InteractionContract(ball, f"TEXT_{ball}")
            self.source.approach(target)
            self.runtime.approach(target)
            self.source.interact(contract)
            self.runtime.interact(contract)
            self._apply(lambda driver: driver.prepare_choice())
            self._choice(f"starter-{species.lower()}-choice-before-no", ball)
            self._apply(lambda driver: driver.choose(False))
            self._record(
                f"starter-{species.lower()}-declined",
                ("map_id", "player_starter", "rival_starter", "party", "has_starter"),
                actor_ids=(ball,),
            )

            self.source.interact(contract)
            self.runtime.interact(contract)
            self._apply(lambda driver: driver.prepare_choice())
            self._choice(f"starter-{species.lower()}-choice-before-yes", ball)
            self._apply(lambda driver: driver.choose(True))
            self._both_advance(
                f"starter-{species.lower()}-selected",
                partial(_starter_selected, expected_species=species, ball=ball),
            )
            self._record(
                f"starter-{species.lower()}-selected",
                ("player_starter", "rival_starter", "party", "has_starter", "flags"),
                actor_ids=(ball,),
            )

            rival_take = InteractionContract("rival_take", "TEXT_OAKSLAB_RIVAL_ILL_TAKE_THIS_ONE")
            self.source.expect_dialog(rival_take)
            self.runtime.expect_dialog(rival_take)
            if self._on_starter_granted is not None:
                self._on_starter_granted(species)
            self._record(
                f"starter-{species.lower()}-party",
                (
                    "player_starter",
                    "rival_starter",
                    "party",
                    "party_levels",
                    "has_starter",
                    "flags",
                ),
                actor_ids=(starter.rival_ball_actor,),
            )
            self._both_advance(
                f"starter-{species.lower()}-rival-counter",
                lambda state: "EVENT_GOT_STARTER" in (state.flags or ()),
            )
            self._record(
                f"starter-{species.lower()}-complete",
                (
                    "map_id",
                    "player_starter",
                    "rival_starter",
                    "party",
                    "party_levels",
                    "has_starter",
                    "flags",
                ),
                actor_ids=(ball, starter.rival_ball_actor),
            )
            source = self.source.capture("starter-boundary")
            runtime = self.runtime.capture("starter-boundary")
            for state in (source, runtime):
                if "EVENT_BATTLED_RIVAL_IN_OAKS_LAB" in (state.flags or ()):
                    raise OracleError(f"{species} oracle crossed the Phase 3A battle boundary")
            if self._on_starter_complete is not None:
                self._on_starter_complete(species)
        self._scenarios.append("all-starters/counter-selection")

    def _choice(self, label: str, ball: str) -> None:
        for driver, recorder in (
            (self.source, self._source_trace),
            (self.runtime, self._runtime_trace),
        ):
            state = driver.capture_choice(label)
            recorder.record(
                project_state(
                    state,
                    label,
                    (
                        "control_mode",
                        "choice_options",
                        "choice_selected",
                        "player_starter",
                        "rival_starter",
                        "party",
                        "has_starter",
                    ),
                    actors=tuple(
                        replace(actor, facing="")
                        for actor in state.actors or ()
                        if actor.id == ball
                    ),
                )
            )

    def _interaction(
        self,
        label: str,
        contract: InteractionContract,
        *,
        target: Position | None = None,
        actor_id: str | None = None,
    ) -> None:
        if (target is None) == (actor_id is None):
            raise OracleError("interaction coverage requires exactly one target kind")
        if target is not None:
            self._apply(lambda driver: driver.approach(target))
            self.source.interact(contract)
            self.runtime.interact(contract)
        else:
            assert actor_id is not None
            self.source.interact_actor(actor_id, contract)
            self.runtime.interact_actor(actor_id, contract)
        self._record(label, ("dialog_id", "control_mode"))
        self._apply(lambda driver: driver.dismiss_dialog())
        self._record(f"{label}-closed", ("control_mode",))

    def _apply(self, operation: Callable[[GameplayDriver], object]) -> None:
        operation(self.source)
        operation(self.runtime)

    def _both_advance(
        self,
        label: str,
        predicate: Callable[[SemanticState], bool],
        *,
        actor_ids: tuple[str, ...] = (),
    ) -> None:
        if actor_ids:
            self._track(
                label + "-path", actor_ids, lambda driver: driver.advance_until(label, predicate)
            )
        else:
            self.source.advance_until(label, predicate)
            self.runtime.advance_until(label, predicate)

    def _track(
        self, label: str, actor_ids: tuple[str, ...], operation: Callable[[GameplayDriver], object]
    ) -> None:
        for driver, recorder in (
            (self.source, self._source_trace),
            (self.runtime, self._runtime_trace),
        ):
            driver.begin_motion(actor_ids)
            try:
                operation(driver)
            finally:
                motion = driver.finish_motion()
                recorder.record(
                    project_state(driver.capture(label), label, ("motion",), motion=motion)
                )

    def _record(
        self,
        hook: str,
        fields: tuple[str, ...],
        *,
        actor_ids: tuple[str, ...] = (),
        actor_facing: bool = False,
    ) -> None:
        for driver, recorder in (
            (self.source, self._source_trace),
            (self.runtime, self._runtime_trace),
        ):
            state = driver.capture(hook)
            overrides: dict[str, object] = {}
            if "flags" in fields:
                overrides["flags"] = tuple(sorted(STORY_FLAGS.intersection(state.flags or ())))
            if actor_ids:
                actors_by_id = {actor.id: actor for actor in state.actors or ()}
                try:
                    actors = tuple(actors_by_id[item] for item in actor_ids)
                except KeyError as error:
                    raise OracleError(f"missing actor {error.args[0]} at {hook}") from error
                overrides["actors"] = (
                    actors if actor_facing else tuple(replace(actor, facing="") for actor in actors)
                )
                fields = (*fields, "actors")
            recorder.record(project_state(state, hook, fields, **overrides))

    @staticmethod
    def _actor_position(state: SemanticState, actor_id: str) -> Position:
        actor = next((actor for actor in state.actors or () if actor.id == actor_id), None)
        if actor is None:
            raise OracleError(f"missing starter actor {actor_id}")
        return Position(x=actor.x, y=actor.y)


def run_phase3a_coverage(
    source: GameplayDriver,
    runtime: GameplayDriver,
    story: StoryDefinition,
    source_revision: str,
    trace_sink: Callable[[SemanticTrace], object] | None = None,
    *,
    on_starter_granted: Callable[[str], None] | None = None,
    on_starter_complete: Callable[[str], None] | None = None,
) -> CoverageResult:
    coverage = Phase3ACoverage(
        source, runtime, story, source_revision, on_starter_granted, on_starter_complete
    )
    try:
        return coverage.run()
    finally:
        if trace_sink is not None:
            trace_sink(coverage._source_trace.finish())
            trace_sink(coverage._runtime_trace.finish())


def frontend_movement_frames(source_root: Path) -> tuple[int, int]:
    """Read the browser's declared timing contract, in Game Boy frame units."""
    duration = re.search(
        r"export const MOVE_DURATION_MS = (\d+);", (source_root / "movement.ts").read_text()
    )
    resample = re.search(
        r"export const TURN_RESAMPLE_DELAY_MS = Math.round\(MOVE_DURATION_MS / (\d+)\);",
        (source_root / "input.ts").read_text(),
    )
    if duration is None or resample is None:
        raise OracleError("frontend movement timing contract could not be read")
    # The DMG advances 4,194,304 cycles/second and 70,224 cycles/frame.
    frames = int(duration.group(1)) / 1000 * 4_194_304 / 70_224
    return round(frames), round(frames / int(resample.group(1)))


def _validate_tile_timing(
    label: str, timing: MovementTiming, count: int, expected_frames: int = 16
) -> None:
    if len(timing.tile_frames) != count:
        raise OracleError(f"{label} captured {len(timing.tile_frames)} of {count} tile timings")
    for index, frames in enumerate(timing.tile_frames, 1):
        _bounded(f"{label} tile {index}", frames, expected_frames - 1, expected_frames + 1)


def _starter_selected(state: SemanticState, *, expected_species: str, ball: str) -> bool:
    return (
        state.player_starter == expected_species
        and not (state.party or ())
        and visible_actor(state, ball) is None
    )


def _bounded(label: str, actual: int, minimum: int, maximum: int) -> None:
    if not minimum <= actual <= maximum:
        raise OracleError(f"{label} took {actual} frames; expected {minimum}..{maximum}")
