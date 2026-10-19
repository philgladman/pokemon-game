import { describe, expect, it, vi } from "vitest";

import {
  FADE_STAGE_MS,
  FADE_STAGES,
  TransitionCoordinator,
  type TransitionOverlay,
} from "../src/transitionCoordinator";
import type { GameRenderer, StateMessage } from "../src/types";

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
        npcs: [],
      },
      player: { position: { x: 1, y: 3 }, facing: "south", sprite: "RED" },
      dialog: null,
    },
  };
}

function overlay(): TransitionOverlay {
  return { hidden: true, style: { opacity: "0" } };
}

const presentation = { resetGait: false };

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

  it("gates immediately, swaps at full black, then runs four fade-in stages", async () => {
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
    expect(phases.at(-1)).toBe("input:true");
    expect(layer).toEqual({ hidden: true, style: { opacity: "0" } });
  });

  it("fades back in and re-enables input when target rendering fails", async () => {
    const layer = overlay();
    const failure = new Error("asset unavailable");
    const renderer: GameRenderer = { update: vi.fn(async () => Promise.reject(failure)) };
    const gate = vi.fn();
    const apply = vi.fn();
    const report = vi.fn();
    const wait = vi.fn(async () => undefined);
    const coordinator = new TransitionCoordinator(
      renderer,
      layer,
      gate,
      apply,
      report,
      wait,
    );

    await coordinator.present(message(), presentation);

    expect(report).toHaveBeenCalledWith(failure);
    expect(apply).not.toHaveBeenCalled();
    expect(wait).toHaveBeenCalledTimes(FADE_STAGES * 2);
    expect(gate.mock.calls).toEqual([[false], [true]]);
    expect(layer.hidden).toBe(true);
    expect(layer.style.opacity).toBe("0");
  });
});
