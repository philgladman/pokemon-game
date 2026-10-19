import type { Position } from "./types";

export const MOVE_DURATION_MS = 268;
export const TILE_PIXELS = 16;
export const MOVEMENT_ADVANCES = 8;
export const PIXELS_PER_ADVANCE = TILE_PIXELS / MOVEMENT_ADVANCES;

export function isAdjacentStep(from: Position, to: Position): boolean {
  return Math.abs(to.x - from.x) + Math.abs(to.y - from.y) === 1;
}

export function movementAdvanceAt(elapsedMs: number): number {
  return Math.min(
    MOVEMENT_ADVANCES,
    Math.max(0, Math.floor((elapsedMs / MOVE_DURATION_MS) * MOVEMENT_ADVANCES)),
  );
}

export function pixelSteppedPosition(
  from: Position,
  to: Position,
  elapsedMs: number,
): Position {
  const advances = movementAdvanceAt(elapsedMs);
  const travelledPixels = advances * PIXELS_PER_ADVANCE;
  const progress = travelledPixels / TILE_PIXELS;
  return {
    x: from.x + (to.x - from.x) * progress,
    y: from.y + (to.y - from.y) * progress,
  };
}
