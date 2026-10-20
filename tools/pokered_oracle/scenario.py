from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from .errors import OracleError
from .trace import SemanticState, SemanticTrace, TraceOrigin, TraceRecorder

ScenarioAction = Literal["tick", "press", "press_until_symbol", "wait_symbol", "capture"]


class ScenarioDriver(Protocol):
    def tick(self, frames: int = 1) -> None: ...

    def press(self, button: str, hold_frames: int = 1, settle_frames: int = 1) -> None: ...

    def wait_for_symbol(self, label: str, *, max_frames: int) -> None: ...

    def press_until_symbol(
        self,
        button: str,
        label: str,
        *,
        max_frames: int,
        hold_frames: int = 1,
        settle_frames: int = 1,
    ) -> None: ...

    def capture(self, hook: str) -> SemanticState: ...


@dataclass(frozen=True)
class ScenarioStep:
    action: ScenarioAction
    label: str
    frames: int = 1
    button: str | None = None
    hold_frames: int = 1
    settle_frames: int = 1

    def __post_init__(self) -> None:
        if not self.label:
            raise OracleError("scenario steps require a label")
        if self.frames < 1:
            raise OracleError("scenario frame counts must be positive")
        if self.action in {"press", "press_until_symbol"} and self.button is None:
            raise OracleError("press scenario steps require a button")
        if self.action not in {"press", "press_until_symbol"} and self.button is not None:
            raise OracleError(f"{self.action} scenario steps cannot specify a button")


@dataclass(frozen=True)
class Scenario:
    id: str
    steps: tuple[ScenarioStep, ...]

    def __post_init__(self) -> None:
        if not self.id or not self.steps:
            raise OracleError("scenarios require an id and at least one step")
        labels = [step.label for step in self.steps if step.action == "capture"]
        if len(labels) != len(set(labels)):
            raise OracleError(f"scenario {self.id!r} has duplicate capture labels")


NEW_GAME_SCENARIO = Scenario(
    id="new-game-ready",
    steps=(
        ScenarioStep(
            action="wait_symbol",
            label="PrepareTitleScreen",
            frames=3_600,
        ),
        ScenarioStep("press_until_symbol", "MainMenu", frames=7_200, button="start"),
        ScenarioStep("press_until_symbol", "StartNewGame", frames=3_600, button="a"),
        ScenarioStep("press_until_symbol", "ChoosePlayerName", frames=18_000, button="a"),
        ScenarioStep("wait_symbol", "HandleMenuInput", frames=1_800),
        ScenarioStep("press", "select-player-name", button="down", hold_frames=2),
        ScenarioStep("press", "confirm-player-name", button="a", hold_frames=2),
        ScenarioStep("press_until_symbol", "ChooseRivalName", frames=18_000, button="a"),
        ScenarioStep("wait_symbol", "HandleMenuInput", frames=1_800),
        ScenarioStep("press", "select-rival-name", button="down", hold_frames=2),
        ScenarioStep("press", "confirm-rival-name", button="a", hold_frames=2),
        ScenarioStep("press_until_symbol", "OverworldLoop", frames=18_000, button="a"),
        ScenarioStep("tick", "settle-first-map-script", frames=60),
        ScenarioStep(action="capture", label="new-game-ready"),
    ),
)


def run_scenario(
    scenario: Scenario,
    driver: ScenarioDriver,
    *,
    origin: TraceOrigin,
    source_revision: str,
) -> SemanticTrace:
    recorder = TraceRecorder(scenario.id, origin, source_revision)
    for step in scenario.steps:
        if step.action == "tick":
            driver.tick(step.frames)
        elif step.action == "press":
            assert step.button is not None
            driver.press(step.button, step.hold_frames, step.settle_frames)
        elif step.action == "press_until_symbol":
            assert step.button is not None
            driver.press_until_symbol(
                step.button,
                step.label,
                max_frames=step.frames,
                hold_frames=step.hold_frames,
                settle_frames=step.settle_frames,
            )
        elif step.action == "wait_symbol":
            driver.wait_for_symbol(step.label, max_frames=step.frames)
        elif step.action == "capture":
            recorder.record(driver.capture(step.label))
        else:  # pragma: no cover - Literal plus frozen construction is defensive
            raise OracleError(f"unsupported scenario action: {step.action}")
    return recorder.finish()
