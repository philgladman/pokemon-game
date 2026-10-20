from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from backend.app.engine.game import ActionResult
from backend.app.models.common import Direction, Position
from backend.app.models.protocol import SessionSnapshot
from backend.app.source.pokered import PokeredSource
from tools.pokered_oracle.coverage import (
    Phase3ACoverage,
    _validate_tile_timing,
    frontend_movement_frames,
    run_phase3a_coverage,
)
from tools.pokered_oracle.errors import OracleError
from tools.pokered_oracle.gameplay import (
    MovementTiming,
    RuntimeGameplayDriver,
    SourceGameplayDriver,
    project_state,
)
from tools.pokered_oracle.runtime import RuntimeAdapter
from tools.pokered_oracle.symbols import Symbol
from tools.pokered_oracle.trace import (
    ActorTrace,
    SemanticState,
    SemanticTrace,
    require_matching_traces,
)


def drivers() -> tuple[RuntimeGameplayDriver, RuntimeGameplayDriver, PokeredSource]:
    source = PokeredSource(Path(__file__).resolve().parents[1] / "external/pokered")
    world, story = source.build_world(), source.build_story()
    return (
        RuntimeGameplayDriver(RuntimeAdapter(world, story), world),
        RuntimeGameplayDriver(RuntimeAdapter(world, story), world),
        source,
    )


def assert_coverage_matches(coverage: Phase3ACoverage) -> None:
    require_matching_traces(coverage._source_trace.finish(), coverage._runtime_trace.finish())


def test_selected_absent_starter_is_compared_but_unselected_fields_are_ignored() -> None:
    expected = project_state(
        SemanticState(1, "before", player_starter=None), "before", ("player_starter",)
    )
    actual = replace(expected, player_starter="CHARMANDER", player_x=99)
    with pytest.raises(OracleError, match="player_starter"):
        require_matching_traces(
            SemanticTrace("test", "pokered", "rev", (expected,)),
            SemanticTrace("test", "runtime", "rev", (actual,)),
        )
    actual = replace(expected, player_x=99)
    require_matching_traces(
        SemanticTrace("test", "pokered", "rev", (expected,)),
        SemanticTrace("test", "runtime", "rev", (actual,)),
    )


def test_changed_fresh_input_is_sent_before_continued_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver, _, _ = drivers()
    original = driver.runtime.move
    calls: list[bool] = []

    def move(direction: Direction, *, continued: bool = False) -> ActionResult:
        calls.append(continued)
        return original(direction, continued=continued)

    monkeypatch.setattr(driver.runtime, "move", move)
    driver.walk_tiles(Direction.WEST, 2)
    assert calls == [False, True, True]
    assert driver.capture("end").player_x == 1


def test_changed_fresh_input_that_walks_first_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    driver, _, _ = drivers()
    original = driver.runtime.move

    def faulty_move(direction: Direction, *, continued: bool = False) -> ActionResult:
        result = original(direction, continued=continued)
        return original(direction, continued=True) if result.action == "turned" else result

    monkeypatch.setattr(driver.runtime, "move", faulty_move)
    with pytest.raises(OracleError, match="must turn before"):
        driver.walk_tiles(Direction.WEST)


def test_house_both_columns_and_atomic_warp_policy_are_compared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, second, source = drivers()
    coverage = Phase3ACoverage(first, second, source.build_story(), source.revision)
    coverage._house()
    assert_coverage_matches(coverage)
    states = {state.hook: state for state in coverage._runtime_trace.finish().states}
    for column in (2, 3):
        motion = states[f"house-{column}-exit-path"].motion
        assert motion is not None
        assert [(point.map_id, point.x, point.y) for point in motion[0].points] == [
            ("REDS_HOUSE_1F", column, 6),
            ("REDS_HOUSE_1F", column, 7),
            ("PALLET_TOWN", 5, 5),
            ("PALLET_TOWN", 5, 6),
        ]
    first, second, source = drivers()
    original = second.exit_reds_house
    monkeypatch.setattr(second, "exit_reds_house", lambda column=2: original(2))
    coverage = Phase3ACoverage(first, second, source.build_story(), source.revision)
    coverage._house()
    with pytest.raises(OracleError, match="motion"):
        assert_coverage_matches(coverage)


def prepare_oak_approach(driver: RuntimeGameplayDriver) -> None:
    driver.walk_to(Position(x=7, y=1))
    driver.exit_reds_house()
    driver.walk_to(Position(x=10, y=2))
    driver.walk_tiles(Direction.NORTH)
    driver.dismiss_dialog()


def test_same_endpoint_wrong_cue_path_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    first, second, source = drivers()
    for driver in (first, second):
        prepare_oak_approach(driver)
    snapshot = second.runtime.snapshot

    def wrong_path() -> SessionSnapshot:
        state = snapshot()
        cue = state.movement_cue
        if cue is None:
            return state
        track = cue.tracks[0]
        # A detour returns to the same tile before the original source path.
        track = track.model_copy(update={"steps": (Direction.EAST, Direction.WEST, *track.steps)})
        return state.model_copy(
            update={"movement_cue": cue.model_copy(update={"tracks": (track,)})}
        )

    monkeypatch.setattr(second.runtime, "snapshot", wrong_path)
    coverage = Phase3ACoverage(first, second, source.build_story(), source.revision)
    coverage._track(
        "approach",
        ("player", "PALLETTOWN_OAK"),
        lambda driver: driver.advance_until(
            "unsafe", lambda state: state.dialog_id == "oak_unsafe"
        ),
    )
    assert first.capture("end").player_x == second.capture("end").player_x
    assert first.runtime.snapshot().map.actors == snapshot().map.actors
    with pytest.raises(OracleError, match="motion"):
        assert_coverage_matches(coverage)


@pytest.mark.parametrize(
    "field,value",
    [
        ("choice_options", ("NO", "YES")),
        ("choice_selected", 1),
        ("player_starter", "CHARMANDER"),
        ("party", ("CHARMANDER",)),
    ],
)
def test_choice_open_state_mutations_are_rejected(
    monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    first, second, source = drivers()
    ball = "OAKSLAB_CHARMANDER_POKE_BALL"
    state = SemanticState(
        1,
        "choice",
        control_mode="choice",
        choice_options=("YES", "NO"),
        choice_selected=0,
        party=(),
        player_starter=None,
        rival_starter=None,
        has_starter=False,
        actors=(),
    )
    monkeypatch.setattr(first, "capture_choice", lambda hook: state)
    monkeypatch.setattr(second, "capture_choice", lambda hook: replace(state, **{field: value}))
    coverage = Phase3ACoverage(first, second, source.build_story(), source.revision)
    coverage._choice("before-no", ball)
    with pytest.raises(OracleError, match=field):
        assert_coverage_matches(coverage)


def test_failure_sink_receives_fresh_partial_traces(monkeypatch: pytest.MonkeyPatch) -> None:
    first, second, source = drivers()

    def fail(self: Phase3ACoverage) -> None:
        self._record("partial", ("map_id",))
        raise OracleError("timeout")

    monkeypatch.setattr(Phase3ACoverage, "_movement", fail)
    traces: list[SemanticTrace] = []
    with pytest.raises(OracleError, match="timeout"):
        run_phase3a_coverage(first, second, source.build_story(), source.revision, traces.append)
    assert [trace.origin for trace in traces] == ["pokered", "runtime"]
    assert all(trace.states[0].hook == "partial" for trace in traces)


class ObservedSource:
    """Read-only source observations, including hook hits and executed buffer bytes."""

    def __init__(self, state: SemanticState) -> None:
        self.state = state
        self.hits = 0
        self.memory: dict[int, int] = {}
        self.symbols = {"wStatusFlags5": Symbol(0, 1), "wNPCMovementDirections2": Symbol(0, 10)}
        self.port = self
        self.observer = None

    def read(self, address: int) -> int:
        return self.memory.get(address, 0)

    def capture(self, hook: str) -> SemanticState:
        return replace(self.state, hook=hook)

    def symbol_hits(self, label: str) -> int:
        return self.hits if label == "WarpFound2" else 0


def test_map_installation_normalization_requires_observed_warp_hook() -> None:
    runtime, _, _ = drivers()
    state = SemanticState(1, "start", map_id="REDS_HOUSE_1F", player_x=2, player_y=6)
    paths = []
    for hook_hit in (0, 1):
        emulator = ObservedSource(state)
        driver = SourceGameplayDriver(emulator, runtime.world)  # type: ignore[arg-type]
        driver.begin_motion(("player",))
        emulator.hits = hook_hit
        driver._observe_source(replace(state, map_id="PALLET_TOWN", player_y=7))
        driver._observe_source(replace(state, map_id="PALLET_TOWN", player_x=5, player_y=5))
        paths.append(driver.finish_motion()[0].points)
    assert paths[0][1].map_id == "PALLET_TOWN"
    assert paths[1][1].map_id == "REDS_HOUSE_1F"
    assert paths[1][-1].map_id == "PALLET_TOWN"


def test_source_synchronized_oak_path_uses_executed_live_buffer_entries() -> None:
    runtime, _, _ = drivers()
    state = SemanticState(
        1,
        "start",
        map_id="PALLET_TOWN",
        player_x=10,
        player_y=1,
        actors=(ActorTrace("PALLETTOWN_OAK", 10, 2, "south", True),),
    )
    emulator = ObservedSource(state)
    driver = SourceGameplayDriver(emulator, runtime.world)  # type: ignore[arg-type]
    driver.begin_motion(("PALLETTOWN_OAK",))
    emulator.memory.update({1: 0x80, 10: 0, 11: 0xC0})
    for index in (0, 1, 2):
        driver._observe_source(replace(state, npc_movement_index=index))
    points = driver.finish_motion()[0].points
    assert [(point.x, point.y) for point in points] == [(10, 2), (10, 3), (11, 3)]


def test_source_oak_approach_uses_live_tiles_instead_of_synchronized_buffer() -> None:
    runtime, _, _ = drivers()
    state = SemanticState(
        1,
        "approach",
        map_id="PALLET_TOWN",
        actors=(ActorTrace("PALLETTOWN_OAK", 10, 8, "north", True),),
    )
    emulator = ObservedSource(state)
    driver = SourceGameplayDriver(emulator, runtime.world)  # type: ignore[arg-type]
    driver.begin_motion(("PALLETTOWN_OAK",))
    # MoveSprite uses bit0 and maintains tile coordinates. Its index/buffer
    # bytes must not activate the separate synchronized movement decoder.
    emulator.memory.update({1: 1, 10: 0xC0, 11: 0xC0})
    for index, y in enumerate((8, 7, 6)):
        driver._observe_source(
            replace(
                state,
                npc_movement_index=index,
                actors=(ActorTrace("PALLETTOWN_OAK", 10, y, "north", True),),
            )
        )
    points = driver.finish_motion()[0].points
    assert [(point.x, point.y) for point in points] == [(10, 8), (10, 7), (10, 6)]


def test_frontend_timing_drift_is_checked_against_source_observation(tmp_path: Path) -> None:
    (tmp_path / "movement.ts").write_text("export const MOVE_DURATION_MS = 268;")
    (tmp_path / "input.ts").write_text(
        "export const TURN_RESAMPLE_DELAY_MS = Math.round(MOVE_DURATION_MS / 8);"
    )
    assert frontend_movement_frames(tmp_path) == (16, 2)
    (tmp_path / "movement.ts").write_text("export const MOVE_DURATION_MS = 536;")
    tile_frames, _ = frontend_movement_frames(tmp_path)
    with pytest.raises(OracleError, match=r"expected 31\.\.33"):
        _validate_tile_timing(
            "observed source tile", MovementTiming(16, None, (16,)), 1, tile_frames
        )
