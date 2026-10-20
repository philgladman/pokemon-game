import { MOVEMENT_ADVANCES, MOVE_DURATION_MS, movementAdvanceAt } from "./movement";
import type { Direction, MovementCue, MovementTrack, Position } from "./types";

export function movementCueDuration(cue: MovementCue): number {
  return Math.max(...cue.tracks.map((track) => track.steps.length), 0) * MOVE_DURATION_MS;
}

export interface MovementTrackState {
  position: Position;
  facing: Direction | null;
  stepIndex: number;
  stepElapsedMs: number;
  complete: boolean;
}

export function movementTrackState(
  track: MovementTrack,
  elapsedMs: number,
  pixelStepped = false,
): MovementTrackState {
  const clampedElapsed = Math.max(0, elapsedMs);
  const elapsedSteps = clampedElapsed / MOVE_DURATION_MS;
  const completed = Math.min(Math.floor(elapsedSteps), track.steps.length);
  let x = track.start.x;
  let y = track.start.y;
  for (let index = 0; index < completed; index += 1) {
    const step = track.steps[index]!;
    if (step === "north") y -= 1;
    if (step === "south") y += 1;
    if (step === "west") x -= 1;
    if (step === "east") x += 1;
  }
  const complete = completed >= track.steps.length;
  if (!complete) {
    const stepElapsedMs = clampedElapsed - completed * MOVE_DURATION_MS;
    const fraction = pixelStepped
      ? movementAdvanceAt(stepElapsedMs) / MOVEMENT_ADVANCES
      : elapsedSteps - completed;
    const step = track.steps[completed]!;
    if (step === "north") y -= fraction;
    if (step === "south") y += fraction;
    if (step === "west") x -= fraction;
    if (step === "east") x += fraction;
  }
  const stepIndex = track.steps.length === 0
    ? 0
    : Math.min(completed, track.steps.length - 1);
  return {
    position: { x, y },
    facing: track.steps[stepIndex] ?? null,
    stepIndex,
    stepElapsedMs: complete
      ? MOVE_DURATION_MS
      : clampedElapsed - completed * MOVE_DURATION_MS,
    complete,
  };
}

export function movementTrackPosition(track: MovementTrack, elapsedMs: number): Position {
  return movementTrackState(track, elapsedMs).position;
}

export function animateMovementCue(
  cue: MovementCue,
  render: (elapsedMs: number) => void,
): Promise<void> {
  const duration = movementCueDuration(cue);
  const startedAt = performance.now();
  return new Promise((resolve) => {
    const frame = (now: number): void => {
      const elapsed = Math.min(duration, now - startedAt);
      render(elapsed);
      if (elapsed >= duration) resolve();
      else requestAnimationFrame(frame);
    };
    if (duration === 0) {
      render(0);
      resolve();
    } else {
      requestAnimationFrame(frame);
    }
  });
}
