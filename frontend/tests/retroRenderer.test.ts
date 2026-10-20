import { afterEach, describe, expect, it, vi } from "vitest";

import {
  MOVEMENT_ADVANCES,
  MOVE_DURATION_MS,
  movementAdvanceAt,
  pixelSteppedPosition,
} from "../src/movement";
import {
  SourceImages,
  nextStandingPhase,
  shouldAnimatePlayerMove,
  spriteFrameAtElapsed,
  spriteFrameForPhase,
  sourceMovementPhase,
  viewportOrigin,
} from "../src/renderers/retro/RetroRenderer";
import type { SourceAsset } from "../src/types";

class FakeImage {
  static readonly instances: FakeImage[] = [];

  naturalWidth = 16;
  naturalHeight = 96;
  src = "";
  private readonly listeners = new Map<string, EventListenerOrEventListenerObject[]>();

  constructor() {
    FakeImage.instances.push(this);
  }

  addEventListener(type: string, listener: EventListenerOrEventListenerObject): void {
    const listeners = this.listeners.get(type) ?? [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }

  dispatch(type: "load" | "error"): void {
    const event = new Event(type);
    for (const listener of this.listeners.get(type) ?? []) {
      if (typeof listener === "function") listener(event);
      else listener.handleEvent(event);
    }
  }
}

afterEach(() => {
  FakeImage.instances.length = 0;
  vi.unstubAllGlobals();
});

describe("retro renderer geometry", () => {
  it("uses the original 160x144 viewport and clamps it to map bounds", () => {
    expect(viewportOrigin(20, 18, 5, 6)).toEqual({ x: 8, y: 32 });
    expect(viewportOrigin(8, 8, 2, 2)).toEqual({ x: 0, y: 0 });
  });

  it("selects the source sprite row for each facing direction", () => {
    expect(spriteFrameForPhase("south", 0).y).toBe(0);
    expect(spriteFrameForPhase("north", 0).y).toBe(16);
    expect(spriteFrameForPhase("east", 0).y).toBe(32);
    expect(spriteFrameForPhase("west", 0).y).toBe(32);
    expect(spriteFrameForPhase("south", 1).y).toBe(48);
    expect(spriteFrameForPhase("north", 1).y).toBe(64);
    expect(spriteFrameForPhase("west", 1).y).toBe(80);
  });

  it("maps all four source phases to the correct sprite frames", () => {
    expect(spriteFrameForPhase("south", 0)).toEqual({
      y: 0,
      mirrored: false,
      walking: false,
      sourcePhase: 0,
    });
    expect(spriteFrameForPhase("south", 1)).toEqual({
      y: 48,
      mirrored: false,
      walking: true,
      sourcePhase: 1,
    });
    expect(spriteFrameForPhase("south", 2)).toEqual({
      y: 0,
      mirrored: false,
      walking: false,
      sourcePhase: 2,
    });
    expect(spriteFrameForPhase("south", 3)).toEqual({
      y: 48,
      mirrored: true,
      walking: true,
      sourcePhase: 3,
    });
    expect(spriteFrameForPhase("north", 3)).toEqual({
      y: 64,
      mirrored: true,
      walking: true,
      sourcePhase: 3,
    });
  });

  it("increments the sprite frame after four source advances and stands at completion", () => {
    const advanceDuration = MOVE_DURATION_MS / MOVEMENT_ADVANCES;
    const expectedPhases = [0, 0, 0, 0, 1, 1, 1, 1, 2];

    for (let advance = 0; advance <= MOVEMENT_ADVANCES; advance += 1) {
      const elapsed = advance * advanceDuration;
      expect(movementAdvanceAt(elapsed)).toBe(advance);
      expect(sourceMovementPhase(elapsed)).toBe(expectedPhases[advance]);
    }

    expect(spriteFrameAtElapsed("south", MOVE_DURATION_MS)).toEqual({
      y: 0,
      mirrored: false,
      walking: false,
      sourcePhase: 2,
    });
  });

  it("alternates the walking foot across continuous tiles", () => {
    const advanceDuration = MOVE_DURATION_MS / MOVEMENT_ADVANCES;
    expect(sourceMovementPhase(0, 0)).toBe(0);
    expect(sourceMovementPhase(advanceDuration * 4, 0)).toBe(1);
    expect(sourceMovementPhase(advanceDuration * 7, 0)).toBe(1);
    expect(sourceMovementPhase(MOVE_DURATION_MS, 0)).toBe(2);
    expect(nextStandingPhase(0)).toBe(2);

    expect(sourceMovementPhase(0, 2)).toBe(2);
    expect(sourceMovementPhase(advanceDuration * 4, 2)).toBe(3);
    expect(sourceMovementPhase(advanceDuration * 7, 2)).toBe(3);
    expect(sourceMovementPhase(MOVE_DURATION_MS, 2)).toBe(0);
    expect(nextStandingPhase(2)).toBe(0);
  });

  it("keeps horizontal orientation stable through both walking phases", () => {
    expect(spriteFrameForPhase("west", 0).mirrored).toBe(false);
    expect(spriteFrameForPhase("west", 1).mirrored).toBe(false);
    expect(spriteFrameForPhase("west", 2).mirrored).toBe(false);
    expect(spriteFrameForPhase("west", 3).mirrored).toBe(false);
    expect(spriteFrameForPhase("east", 0).mirrored).toBe(true);
    expect(spriteFrameForPhase("east", 1).mirrored).toBe(true);
    expect(spriteFrameForPhase("east", 2).mirrored).toBe(true);
    expect(spriteFrameForPhase("east", 3).mirrored).toBe(true);
  });

  it("moves in eight two-pixel advances over the source-like cadence", () => {
    const from = { x: 2, y: 3 };
    const to = { x: 3, y: 3 };
    const advanceDuration = MOVE_DURATION_MS / MOVEMENT_ADVANCES;
    expect(MOVE_DURATION_MS).toBe(268);
    for (let advance = 0; advance <= MOVEMENT_ADVANCES; advance += 1) {
      expect(pixelSteppedPosition(from, to, advance * advanceDuration)).toEqual({
        x: 2 + (advance * 2) / 16,
        y: 3,
      });
    }
    expect(pixelSteppedPosition(from, to, advanceDuration - 0.01)).toEqual(from);
  });

  it("animates only adjacent moves on the same map with unchanged resources", () => {
    expect(shouldAnimatePlayerMove("A", "A", { x: 1, y: 1 }, { x: 1, y: 2 })).toBe(true);
    expect(shouldAnimatePlayerMove("A", "B", { x: 1, y: 1 }, { x: 1, y: 2 })).toBe(false);
    expect(shouldAnimatePlayerMove("A", "A", { x: 1, y: 1 }, { x: 3, y: 1 })).toBe(false);
    expect(shouldAnimatePlayerMove("A", "A", { x: 1, y: 1 }, { x: 1, y: 2 }, true)).toBe(
      false,
    );
    expect(
      shouldAnimatePlayerMove("A", "A", { x: 1, y: 1 }, { x: 1, y: 2 }, false, true),
    ).toBe(false);
  });
});

describe("SourceImages", () => {
  it("retries a failed request and reuses the successful image cache", async () => {
    vi.stubGlobal("Image", FakeImage);
    const images = new SourceImages();
    const asset: SourceAsset = {
      kind: "sprite",
      name: "red",
      url: "/source-assets/sprites/red.png",
    };

    const first = images.load(asset);
    const firstFailure = expect(first).rejects.toThrow(`Unable to load ${asset.url}`);
    FakeImage.instances[0]!.dispatch("error");
    await firstFailure;

    const second = images.load(asset);
    expect(second).not.toBe(first);
    expect(FakeImage.instances).toHaveLength(2);
    const recovered = FakeImage.instances[1]!;
    recovered.dispatch("load");
    await expect(second).resolves.toBe(recovered);
    expect(images.get(asset.url)).toBe(recovered);

    await expect(images.load(asset)).resolves.toBe(recovered);
    expect(FakeImage.instances).toHaveLength(2);
  });
});
