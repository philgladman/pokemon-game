from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from .errors import OracleError

TraceOrigin = Literal["pokered", "runtime"]


@dataclass(frozen=True)
class ActorTrace:
    id: str
    x: int
    y: int
    facing: str
    visible: bool


@dataclass(frozen=True)
class SemanticState:
    frame: int
    hook: str
    input: str | None = None
    map_id: str | None = None
    player_x: int | None = None
    player_y: int | None = None
    facing: str | None = None
    walk_counter: int | None = None
    map_script: int | None = None
    joy_ignore: int | None = None
    simulated_joypad_index: int | None = None
    npc_movement_index: int | None = None
    actors: tuple[ActorTrace, ...] | None = None
    flags: tuple[str, ...] | None = None
    player_starter: str | None = None
    rival_starter: str | None = None
    party: tuple[str, ...] | None = None

    def semantic_values(self, *, include_frame: bool = False) -> dict[str, object]:
        values = asdict(self)
        if not include_frame:
            values.pop("frame")
        return values


@dataclass(frozen=True)
class SemanticTrace:
    scenario: str
    origin: TraceOrigin
    source_revision: str
    states: tuple[SemanticState, ...]
    metadata: dict[str, str] = field(default_factory=dict)

    def write(self, path: Path, cache_root: Path) -> None:
        resolved_path = path.resolve()
        resolved_cache = cache_root.resolve()
        if resolved_cache not in resolved_path.parents:
            raise OracleError(f"oracle traces must stay under {resolved_cache}: {resolved_path}")
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        resolved_path.write_text(
            json.dumps(asdict(self), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


class TraceRecorder:
    def __init__(self, scenario: str, origin: TraceOrigin, source_revision: str) -> None:
        self.scenario = scenario
        self.origin = origin
        self.source_revision = source_revision
        self._states: list[SemanticState] = []

    def record(self, state: SemanticState) -> None:
        if self._states and self._states[-1].semantic_values() == state.semantic_values():
            return
        self._states.append(state)

    def finish(self, metadata: dict[str, str] | None = None) -> SemanticTrace:
        return SemanticTrace(
            scenario=self.scenario,
            origin=self.origin,
            source_revision=self.source_revision,
            states=tuple(self._states),
            metadata={} if metadata is None else dict(metadata),
        )


@dataclass(frozen=True)
class TraceDifference:
    state_index: int
    field: str
    expected: object
    actual: object

    def __str__(self) -> str:
        return (
            f"state[{self.state_index}].{self.field}: "
            f"expected {self.expected!r}, actual {self.actual!r}"
        )


def compare_traces(
    expected: SemanticTrace,
    actual: SemanticTrace,
    *,
    compare_frames: bool = False,
) -> tuple[TraceDifference, ...]:
    differences: list[TraceDifference] = []
    if expected.scenario != actual.scenario:
        differences.append(TraceDifference(-1, "scenario", expected.scenario, actual.scenario))
    if expected.source_revision != actual.source_revision:
        differences.append(
            TraceDifference(
                -1,
                "source_revision",
                expected.source_revision,
                actual.source_revision,
            )
        )
    if len(expected.states) != len(actual.states):
        differences.append(
            TraceDifference(-1, "state_count", len(expected.states), len(actual.states))
        )
    for index, (expected_state, actual_state) in enumerate(
        zip(expected.states, actual.states, strict=False)
    ):
        expected_values = expected_state.semantic_values(include_frame=compare_frames)
        actual_values = actual_state.semantic_values(include_frame=compare_frames)
        for field_name, expected_value in expected_values.items():
            if expected_value is None:
                continue
            actual_value = actual_values[field_name]
            if expected_value != actual_value:
                differences.append(TraceDifference(index, field_name, expected_value, actual_value))
    return tuple(differences)


def require_matching_traces(
    expected: SemanticTrace,
    actual: SemanticTrace,
    *,
    compare_frames: bool = False,
) -> None:
    differences = compare_traces(expected, actual, compare_frames=compare_frames)
    if differences:
        compact = "\n".join(str(item) for item in differences[:12])
        suffix = "\n..." if len(differences) > 12 else ""
        raise OracleError(f"semantic trace mismatch:\n{compact}{suffix}")
