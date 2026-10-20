import { describe, expect, it, vi } from "vitest";

import { CueAcknowledger } from "../src/cueAcknowledgement";
import { MOVE_DURATION_MS } from "../src/movement";
import {
  movementCueDuration,
  movementTrackPosition,
  movementTrackState,
} from "../src/scriptedMovement";
import type { ClientMessage, MovementCue, SessionSnapshot } from "../src/types";

const cue: MovementCue = {
  id: "cue-7",
  tracks: [
    { actor_id: "player", start: { x: 1, y: 2 }, steps: ["north", "east"] },
    { actor_id: "oak", start: { x: 3, y: 4 }, steps: ["south"] },
  ],
};

const escortCue: MovementCue = {
  id: "oak-escort",
  tracks: [
    {
      actor_id: "player",
      start: { x: 10, y: 1 },
      steps: [
        "south", "south", "south", "south", "south", "south",
        "west",
        "south", "south", "south", "south", "south",
        "east", "east", "east",
        "north",
      ],
    },
    {
      actor_id: "PALLETTOWN_OAK",
      start: { x: 10, y: 2 },
      steps: [
        "south", "south", "south", "south", "south",
        "west",
        "south", "south", "south", "south", "south",
        "east", "east", "east",
        "north",
      ],
    },
  ],
};

function snapshot(activeCue: MovementCue | null): SessionSnapshot {
  return {
    map: {
      id: "MAP",
      source_name: "Map",
      kind: "outdoor",
      last_map_target: null,
      width: 4,
      height: 4,
      walkable: [],
      actors: [],
    },
    player: { position: { x: 1, y: 2 }, facing: "north", sprite: "RED" },
    dialog: null,
    choice: null,
    control_mode: activeCue === null ? "free" : "scripted_movement",
    movement_cue: activeCue,
    transition: null,
    flags: [],
    has_starter: false,
    player_starter: null,
    rival_starter: null,
    party: [],
  };
}

describe("scripted movement", () => {
  it("uses the longest simultaneous track and interpolates each source step", () => {
    expect(movementCueDuration(cue)).toBe(MOVE_DURATION_MS * 2);
    expect(movementTrackPosition(cue.tracks[0]!, MOVE_DURATION_MS / 2)).toEqual({
      x: 1,
      y: 1.5,
    });
    expect(movementTrackPosition(cue.tracks[0]!, MOVE_DURATION_MS)).toEqual({ x: 1, y: 1 });
    expect(movementTrackPosition(cue.tracks[0]!, MOVE_DURATION_MS * 2)).toEqual({ x: 2, y: 1 });
    expect(movementTrackPosition(cue.tracks[1]!, MOVE_DURATION_MS * 2)).toEqual({ x: 3, y: 5 });
  });

  it("exposes the active source step, facing, and per-step animation time", () => {
    expect(movementTrackState(cue.tracks[0]!, MOVE_DURATION_MS / 2)).toEqual({
      position: { x: 1, y: 1.5 },
      facing: "north",
      stepIndex: 0,
      stepElapsedMs: MOVE_DURATION_MS / 2,
      complete: false,
    });
    expect(movementTrackState(cue.tracks[0]!, MOVE_DURATION_MS)).toEqual({
      position: { x: 1, y: 1 },
      facing: "east",
      stepIndex: 1,
      stepElapsedMs: 0,
      complete: false,
    });
    expect(movementTrackState(cue.tracks[0]!, MOVE_DURATION_MS * 2)).toEqual({
      position: { x: 2, y: 1 },
      facing: "east",
      stepIndex: 1,
      stepElapsedMs: MOVE_DURATION_MS,
      complete: true,
    });
  });

  it("can quantize retro cue motion to the source's eight two-pixel advances", () => {
    const firstTrack = cue.tracks[0]!;
    expect(movementTrackState(firstTrack, MOVE_DURATION_MS / 8 - 0.01, true).position).toEqual({
      x: 1,
      y: 2,
    });
    expect(movementTrackState(firstTrack, MOVE_DURATION_MS / 8, true).position).toEqual({
      x: 1,
      y: 1.875,
    });
  });

  it("holds Oak at the door while Red lands on the warp on the final escort tick", () => {
    const [player, oak] = escortCue.tracks;
    expect(movementCueDuration(escortCue)).toBe(MOVE_DURATION_MS * 16);
    expect(movementTrackState(player!, MOVE_DURATION_MS * 15)).toMatchObject({
      position: { x: 12, y: 12 },
      facing: "north",
      complete: false,
    });
    expect(movementTrackState(oak!, MOVE_DURATION_MS * 15)).toMatchObject({
      position: { x: 12, y: 11 },
      facing: "north",
      complete: true,
    });
    expect(movementTrackState(player!, MOVE_DURATION_MS * 16)).toMatchObject({
      position: { x: 12, y: 11 },
      facing: "north",
      complete: true,
    });
    expect(movementTrackState(oak!, MOVE_DURATION_MS * 16)).toMatchObject({
      position: { x: 12, y: 11 },
      facing: "north",
      complete: true,
    });
  });

  it("acknowledges only a successfully sent rendered cue and deduplicates it", () => {
    const sent: ClientMessage[] = [];
    let succeeds = false;
    const send = vi.fn((message: ClientMessage) => {
      sent.push(message);
      return succeeds;
    });
    const acknowledger = new CueAcknowledger(send, () => "request-1");

    expect(acknowledger.rendered(snapshot(cue))).toBe(false);
    succeeds = true;
    expect(acknowledger.rendered(snapshot(cue))).toBe(true);
    expect(acknowledger.rendered(snapshot(cue))).toBe(false);
    expect(sent.at(-1)).toEqual({
      type: "acknowledge_cue",
      request_id: "request-1",
      cue_id: "cue-7",
    });
  });
});
