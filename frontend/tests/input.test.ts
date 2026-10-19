import { describe, expect, it, vi } from "vitest";

import {
  HeldInputController,
  TURN_RESAMPLE_DELAY_MS,
  type InputClock,
} from "../src/input";
import { MOVE_DURATION_MS } from "../src/movement";
import type { ClientMessage, DialogState, StateMessage } from "../src/types";

class ManualClock implements InputClock {
  currentTime = 0;
  private nextTimer = 1;
  private readonly timers = new Map<number, { at: number; callback: () => void }>();

  now(): number {
    return this.currentTime;
  }

  setTimer(callback: () => void, delayMs: number): number {
    const timer = this.nextTimer;
    this.nextTimer += 1;
    this.timers.set(timer, { at: this.currentTime + delayMs, callback });
    return timer;
  }

  clearTimer(timer: number): void {
    this.timers.delete(timer);
  }

  advance(milliseconds: number): void {
    this.currentTime += milliseconds;
    const ready = [...this.timers.entries()]
      .filter(([, timer]) => timer.at <= this.currentTime)
      .sort(([, left], [, right]) => left.at - right.at);
    for (const [id, timer] of ready) {
      if (!this.timers.delete(id)) continue;
      timer.callback();
    }
  }
}

function state(
  requestId: string | null,
  action = "moved",
  dialog: DialogState | null = null,
): StateMessage {
  return {
    type: "state",
    request_id: requestId,
    state_version: 1,
    action,
    reason: null,
    state: {
      map: {
        id: "PALLET_TOWN",
        source_name: "Pallet Town",
        kind: "outdoor",
        last_map_target: null,
        width: 10,
        height: 10,
        walkable: [],
        npcs: [],
      },
      player: { position: { x: 5, y: 6 }, facing: "south", sprite: "SPRITE_RED" },
      dialog,
    },
  };
}

function harness(sendResult = true): {
  controller: HeldInputController;
  clock: ManualClock;
  sent: ClientMessage[];
} {
  const sent: ClientMessage[] = [];
  const clock = new ManualClock();
  let nextId = 1;
  const controller = new HeldInputController(
    (message) => {
      sent.push(message);
      return sendResult;
    },
    () => `request-${nextId++}`,
    clock,
  );
  return { controller, clock, sent };
}

describe("HeldInputController", () => {
  it.each([
    ["ArrowUp", "north"],
    ["KeyW", "north"],
    ["ArrowDown", "south"],
    ["KeyS", "south"],
    ["ArrowLeft", "west"],
    ["KeyA", "west"],
    ["ArrowRight", "east"],
    ["KeyD", "east"],
  ])("starts a new input sequence for physical key %s", (code, direction) => {
    const { controller, sent } = harness();
    expect(controller.keyDown(code)).toBe(true);
    expect(sent).toEqual([
      { type: "move", request_id: "request-1", direction, continued: false },
    ]);
  });

  it("keeps a released changed-direction tap turn-only", () => {
    const { controller, clock, sent } = harness();
    controller.keyDown("ArrowUp");
    controller.keyUp("ArrowUp");
    const presentation = controller.handleState(state("request-1", "turned"));
    clock.advance(TURN_RESAMPLE_DELAY_MS * 2);
    expect(presentation).toEqual({ resetGait: true });
    expect(sent).toHaveLength(1);
  });

  it("resamples a held turn after about two Game Boy frames, without a 502ms delay", () => {
    const { controller, clock, sent } = harness();
    controller.keyDown("ArrowUp");
    controller.handleState(state("request-1", "turned"));
    clock.advance(TURN_RESAMPLE_DELAY_MS - 1);
    expect(sent).toHaveLength(1);
    clock.advance(1);
    expect(TURN_RESAMPLE_DELAY_MS).toBe(34);
    expect(sent[1]).toEqual({
      type: "move",
      request_id: "request-2",
      direction: "north",
      continued: true,
    });
  });

  it("does not reset gait merely because a continued sample reports turned", () => {
    const { controller, clock } = harness();
    controller.keyDown("ArrowUp");
    expect(controller.handleState(state("request-1", "turned"))).toEqual({
      resetGait: true,
    });
    clock.advance(TURN_RESAMPLE_DELAY_MS);

    expect(controller.handleState(state("request-2", "turned"))).toEqual({
      resetGait: false,
    });
  });

  it("paces successful held movement at one acknowledged tile per 268ms", () => {
    const { controller, clock, sent } = harness();
    controller.keyDown("ArrowDown");
    controller.handleState(state("request-1", "moved"));
    clock.advance(MOVE_DURATION_MS - 1);
    expect(sent).toHaveLength(1);
    clock.advance(1);
    expect(sent[1]).toMatchObject({ direction: "south", continued: true });
    controller.handleState(state("request-2", "moved"));
    clock.advance(MOVE_DURATION_MS);
    expect(sent[2]).toMatchObject({ direction: "south", continued: true });
  });

  it("requires a correlated acknowledgement before sending another move", () => {
    const { controller, clock, sent } = harness();
    controller.keyDown("ArrowDown");
    clock.advance(MOVE_DURATION_MS * 2);
    controller.handleState(state("different-request", "moved"));
    expect(sent).toHaveLength(1);
    controller.handleState(state("request-1", "moved"));
    clock.advance(MOVE_DURATION_MS);
    expect(sent).toHaveLength(2);
  });

  it("defers neutral until an active tile ends and cancels it when repressed", () => {
    const { controller, clock, sent } = harness();
    controller.keyDown("ArrowDown");
    controller.handleState(state("request-1", "moved"));
    clock.advance(100);
    controller.keyUp("ArrowDown");
    clock.advance(100);
    controller.keyDown("ArrowDown");
    clock.advance(MOVE_DURATION_MS - 201);
    expect(sent).toHaveLength(1);
    clock.advance(1);
    expect(sent[1]).toMatchObject({ direction: "south", continued: true });
  });

  it("rearms a new sequence once released movement reaches its action deadline", () => {
    const { controller, clock, sent } = harness();
    controller.keyDown("ArrowDown");
    controller.handleState(state("request-1", "moved"));
    controller.keyUp("ArrowDown");
    clock.advance(MOVE_DURATION_MS);
    controller.keyDown("ArrowUp");
    expect(sent[1]).toMatchObject({ direction: "north", continued: false });
  });

  it("allows further direction changes to move in the same continuous sequence", () => {
    const { controller, clock, sent } = harness();
    controller.keyDown("ArrowUp");
    controller.handleState(state("request-1", "turned"));
    controller.keyDown("ArrowLeft");
    controller.keyUp("ArrowUp");
    clock.advance(TURN_RESAMPLE_DELAY_MS);
    expect(sent[1]).toMatchObject({ direction: "west", continued: true });
    expect(controller.handleState(state("request-2", "moved"))).toEqual({
      resetGait: false,
    });
  });

  it("uses the source south, north, west, east direction priority", () => {
    const { controller, clock, sent } = harness();
    controller.keyDown("ArrowRight");
    controller.handleState(state("request-1", "turned"));
    controller.keyDown("ArrowLeft");
    controller.keyDown("ArrowUp");
    controller.keyDown("ArrowDown");
    clock.advance(TURN_RESAMPLE_DELAY_MS);
    expect(sent[1]).toMatchObject({ direction: "south", continued: true });
  });

  it("defers a queued interaction until a successful movement tile is presented", () => {
    const { controller, clock, sent } = harness();
    controller.keyDown("ArrowDown");
    controller.handleState(state("request-1", "moved"));
    controller.keyDown("Space");
    controller.keyUp("Space");
    clock.advance(MOVE_DURATION_MS - 1);
    expect(sent).toHaveLength(1);
    clock.advance(1);
    expect(sent[1]).toEqual({ type: "interact", request_id: "request-2" });
  });

  it("resets continuity for transitions, dialogs, focus loss, and input gating", () => {
    const { controller, sent } = harness();
    controller.keyDown("ArrowDown");
    expect(controller.handleState(state("request-1", "transitioned"))).toEqual({
      resetGait: true,
    });
    controller.keyDown("ArrowDown");
    expect(sent[1]).toMatchObject({ continued: false });
    const dialog = { interaction_id: "npc", pages: ["Hello"], page_index: 0 };
    controller.handleState(state("request-2", "dialog_opened", dialog));
    controller.reset();
    controller.keyDown("ArrowDown");
    expect(sent[2]).toMatchObject({ continued: false });
    controller.setEnabled(false);
    controller.setEnabled(true);
    controller.keyDown("ArrowDown", true);
    expect(sent).toHaveLength(3);
  });

  it("deduplicates browser repeats and physical aliases for one direction", () => {
    const { controller, sent } = harness();
    controller.keyDown("ArrowUp");
    controller.keyDown("ArrowUp", true);
    controller.keyDown("KeyW");
    expect(sent).toHaveLength(1);
  });

  it("clears input after a failed or throwing send", () => {
    const failed = harness(false);
    failed.controller.keyDown("ArrowUp");
    failed.clock.advance(MOVE_DURATION_MS * 2);
    expect(failed.sent).toHaveLength(1);

    const send = vi.fn(() => {
      throw new Error("socket failed");
    });
    const controller = new HeldInputController(send, () => "request", new ManualClock());
    expect(() => controller.keyDown("ArrowUp")).not.toThrow();
    expect(send).toHaveBeenCalledTimes(1);
  });
});
