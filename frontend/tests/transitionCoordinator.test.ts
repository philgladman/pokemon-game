import { describe, expect, it, vi } from "vitest";

import {
  FADE_STAGE_MS,
  FADE_STAGES,
  TransitionCoordinator,
  type TransitionOverlay,
} from "../src/transitionCoordinator";
import { HeldInputController } from "../src/input";
import { TransitionAcknowledger } from "../src/transitionAcknowledgement";
import type { ClientMessage, GameRenderer, StateMessage } from "../src/types";

function message(action = "transitioned"): StateMessage {
  return {
    type: "state",
    request_id: "request-1",
    state_version: 1,
    action,
    reason: null,
    state: {
      map: {
        id: "ROOM",
        source_name: "Room",
        kind: "indoor",
        last_map_target: "OUTSIDE",
        width: 4,
        height: 4,
        walkable: [],
        actors: [],
      },
      player: { position: { x: 1, y: 3 }, facing: "south", sprite: "RED" },
      dialog: null,
      choice: null,
      control_mode: "free",
      movement_cue: null,
      transition: action === "transitioned" ? { id: "transition-1" } : null,
      flags: [],
      has_starter: false,
      player_starter: null,
      rival_starter: null,
      party: [],
      money: 3000,
      battle: null,
    },
  };
}

function overlay(): TransitionOverlay {
  return { hidden: true, style: { opacity: "0" } };
}

const presentation = { resetGait: false };

function movementCueMessage(): StateMessage {
  const state = message("scripted_movement");
  state.state.control_mode = "scripted_movement";
  state.state.movement_cue = {
    id: "cue-1",
    tracks: [
      {
        actor_id: "player",
        start: { x: 1, y: 3 },
        steps: ["north", "north"],
      },
    ],
  };
  return state;
}

describe("TransitionCoordinator", () => {
  it("renders ordinary state without gating or fading", async () => {
    const renderer: GameRenderer = { update: vi.fn(async () => undefined) };
    const layer = overlay();
    const gate = vi.fn();
    const apply = vi.fn();
    const wait = vi.fn(async () => undefined);
    const coordinator = new TransitionCoordinator(
      renderer,
      layer,
      gate,
      apply,
      vi.fn(),
      wait,
    );
    const state = message("moved");

    await coordinator.present(state, presentation);

    expect(renderer.update).toHaveBeenCalledWith(state.state, presentation);
    expect(apply).toHaveBeenCalledWith(state);
    expect(gate).not.toHaveBeenCalled();
    expect(wait).not.toHaveBeenCalled();
    expect(layer.hidden).toBe(true);
  });

  it("gates immediately, swaps at full black, and unlocks after the transition response", async () => {
    const layer = overlay();
    const phases: string[] = [];
    const renderer: GameRenderer = {
      update: vi.fn(async () => {
        phases.push(`render:${layer.style.opacity}`);
      }),
    };
    const gate = vi.fn((enabled: boolean) => phases.push(`input:${enabled}`));
    const apply = vi.fn(() => phases.push("interface"));
    const wait = vi.fn(async (milliseconds: number) => {
      phases.push(`wait:${layer.style.opacity}:${milliseconds}`);
    });
    const coordinator = new TransitionCoordinator(
      renderer,
      layer,
      gate,
      apply,
      vi.fn(),
      wait,
      { transition: () => true },
    );

    const presenting = coordinator.present(message(), presentation);
    expect(gate).toHaveBeenCalledWith(false);
    await presenting;

    expect(wait).toHaveBeenCalledTimes(FADE_STAGES * 2);
    expect(wait).toHaveBeenCalledWith(FADE_STAGE_MS);
    expect(
      phases.filter((phase) => phase.startsWith("wait:")).map((phase) => phase.split(":")[1]),
    ).toEqual(["0.25", "0.5", "0.75", "1", "0.75", "0.5", "0.25", "0"]);
    expect(phases).toContain("render:1");
    expect(phases.indexOf("interface")).toBeGreaterThan(phases.indexOf("render:1"));
    expect(phases).not.toContain("input:true");
    expect(layer).toEqual({ hidden: true, style: { opacity: "0" } });

    await coordinator.present(message("scripted_movement"), presentation);
    expect(phases.at(-1)).toBe("input:true");
  });

  it("keeps a failed destination uncommitted and acknowledges exactly once after retry", async () => {
    const layer = overlay();
    const failure = new Error("asset unavailable");
    const renderer: GameRenderer = {
      update: vi.fn().mockRejectedValueOnce(failure).mockResolvedValue(undefined),
    };
    const gate = vi.fn();
    const apply = vi.fn();
    const report = vi.fn();
    const wait = vi.fn(async () => undefined);
    const sent: ClientMessage[] = [];
    const acknowledger = new TransitionAcknowledger(
      (clientMessage) => {
        sent.push(clientMessage);
        return true;
      },
      () => "retry-request",
    );
    const coordinator = new TransitionCoordinator(
      renderer,
      layer,
      gate,
      apply,
      report,
      wait,
      { transition: (state) => acknowledger.rendered(state.state) },
    );
    const transitioned = message();

    await coordinator.present(transitioned, presentation);

    expect(report).toHaveBeenCalledWith(failure);
    expect(apply).not.toHaveBeenCalled();
    expect(wait).toHaveBeenCalledTimes(FADE_STAGES);
    expect(gate.mock.calls).toEqual([[false]]);
    expect(sent).toEqual([]);
    expect(layer.hidden).toBe(true);
    expect(layer.style.opacity).toBe("0");
    expect(coordinator.hasPendingRetry()).toBe(true);

    const retry = coordinator.retryPending();
    expect(await coordinator.retryPending()).toBe(false);
    expect(await retry).toBe(true);
    expect(apply).toHaveBeenCalledTimes(1);
    expect(wait).toHaveBeenCalledTimes(FADE_STAGES * 3);
    expect(sent).toEqual([
      {
        type: "acknowledge_transition",
        request_id: "retry-request",
        transition_id: "transition-1",
      },
    ]);
    expect(gate.mock.calls).toEqual([[false], [false]]);
    expect(coordinator.hasPendingRetry()).toBe(false);
    expect(await coordinator.retryPending()).toBe(false);

    await coordinator.present(message("transition_completed"), presentation);
    expect(gate.mock.calls).toEqual([[false], [false], [true]]);
  });

  it("keeps input gated until the rendered transition is acknowledged by the server", async () => {
    const renderer: GameRenderer = { update: vi.fn(async () => undefined) };
    const gate = vi.fn();
    const acknowledge = vi.fn(() => true);
    const coordinator = new TransitionCoordinator(
      renderer,
      overlay(),
      gate,
      vi.fn(),
      vi.fn(),
      async () => undefined,
      { transition: acknowledge },
    );
    const transitioned = message();

    await coordinator.present(transitioned, presentation);

    expect(acknowledge).toHaveBeenCalledWith(transitioned);
    expect(gate.mock.calls).toEqual([[false]]);

    const continued = message("scripted_movement");
    await coordinator.present(continued, presentation);
    expect(gate.mock.calls).toEqual([[false], [true]]);
  });

  it("hides prior dialog before cue animation completes and acknowledges only afterward", async () => {
    let finishAnimation = (): void => {
      throw new Error("animation did not start");
    };
    const renderer: GameRenderer = {
      update: vi.fn()
        .mockResolvedValueOnce(undefined)
        .mockImplementationOnce(
          () => new Promise<void>((resolve) => {
            finishAnimation = resolve;
          }),
        ),
    };
    let dialogVisible = false;
    const apply = vi.fn((state: StateMessage) => {
      dialogVisible = state.state.dialog !== null;
    });
    const gate = vi.fn();
    const acknowledgeCue = vi.fn(() => true);
    const sent: ClientMessage[] = [];
    const input = new HeldInputController(
      (clientMessage) => {
        sent.push(clientMessage);
        return true;
      },
      () => "request-input",
    );
    const coordinator = new TransitionCoordinator(
      renderer,
      overlay(),
      gate,
      apply,
      vi.fn(),
      async () => undefined,
      { movementCue: acknowledgeCue },
    );
    const dialog = message("dialog_opened");
    dialog.state.dialog = {
      interaction_id: "oak_unsafe",
      pages: ["Here, come with me!"],
      page_index: 0,
    };
    dialog.state.control_mode = "dialog";
    input.handleState(dialog);
    await coordinator.present(dialog, presentation);
    expect(dialogVisible).toBe(true);

    const cue = movementCueMessage();
    input.handleState(cue);
    const presenting = coordinator.present(cue, presentation);
    await vi.waitFor(() => expect(renderer.update).toHaveBeenCalledTimes(2));

    expect(dialogVisible).toBe(false);
    expect(apply).toHaveBeenCalledTimes(2);
    expect(acknowledgeCue).not.toHaveBeenCalled();
    expect(input.keyDown("ArrowUp")).toBe(true);
    expect(sent).toEqual([]);
    expect(gate).not.toHaveBeenCalled();

    finishAnimation();
    await presenting;

    expect(apply).toHaveBeenCalledTimes(2);
    expect(acknowledgeCue).toHaveBeenCalledOnce();
    expect(acknowledgeCue).toHaveBeenCalledWith(cue);
    expect(gate).not.toHaveBeenCalled();
  });

  it("does not acknowledge a movement cue when renderer animation fails", async () => {
    const failure = new Error("animation failed");
    const renderer: GameRenderer = { update: vi.fn().mockRejectedValue(failure) };
    const apply = vi.fn();
    const report = vi.fn();
    const acknowledgeCue = vi.fn(() => true);
    const coordinator = new TransitionCoordinator(
      renderer,
      overlay(),
      vi.fn(),
      apply,
      report,
      async () => undefined,
      { movementCue: acknowledgeCue },
    );
    const cue = movementCueMessage();

    await coordinator.present(cue, presentation);

    expect(apply).toHaveBeenCalledOnce();
    expect(apply).toHaveBeenCalledWith(cue);
    expect(report).toHaveBeenCalledWith(failure);
    expect(acknowledgeCue).not.toHaveBeenCalled();
  });

  it("correlates and deduplicates rendered transition acknowledgements", () => {
    const sent: ClientMessage[] = [];
    const acknowledger = new TransitionAcknowledger(
      (clientMessage) => {
        sent.push(clientMessage);
        return true;
      },
      () => "request-9",
    );
    const transitioned = message();

    expect(acknowledger.rendered(transitioned.state)).toBe(true);
    expect(acknowledger.rendered(transitioned.state)).toBe(false);
    expect(sent).toEqual([
      {
        type: "acknowledge_transition",
        request_id: "request-9",
        transition_id: "transition-1",
      },
    ]);
  });
});
