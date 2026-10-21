import { describe, expect, it, vi } from "vitest";
import { BattlePresentation, type BattleDisplay, type BattleSurface } from "../src/battlePresentation";
import type { BattleSnapshot, ClientMessage } from "../src/types";

function snapshot(): BattleSnapshot {
  const stats = { hp: 20, attack: 12, defense: 11, speed: 10, special: 13 };
  const pokemon = {
    species: "BULBASAUR", name: "BULBASAUR", level: 5, hp: 20, max_hp: 20,
    stats, experience: 135, stat_experience: { hp: 0, attack: 0, defense: 0, speed: 0, special: 0 },
    image_url: "/assets/back.png",
    moves: [{ slot: 0, name: "TACKLE", pp: 10, max_pp: 35 }, { slot: 1, name: "GROWL", pp: 0, max_pp: 40 }],
  };
  return {
    id: "battle-1", turn: 0, outcome: "ongoing", player: pokemon,
    rival: { ...pokemon, name: "CHARMANDER", image_url: "/assets/front.png" },
    action_token: null,
    batch: { id: "batch-1", frames: [
      { text: "Rival challenges you!", player_hp: 20, rival_hp: 20, player_pp: [10, 0],
        player_level: 5, player_max_hp: 20, player_stats: stats,
        rival_level: 5, rival_max_hp: 20, rival_stats: stats },
      { text: "A hit!", player_hp: 16, rival_hp: 12, player_pp: [9, 0],
        player_level: 5, player_max_hp: 20, player_stats: stats,
        rival_level: 5, rival_max_hp: 20, rival_stats: stats },
    ] },
  };
}

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => { resolve = done; });
  return { promise, resolve };
}

function harness() {
  let display!: BattleDisplay;
  const surface: BattleSurface = {
    loadAssets: vi.fn(async () => undefined),
    render: vi.fn((next) => { display = next; }),
    painted: vi.fn(async () => undefined),
  };
  const messages: ClientMessage[] = [];
  const send = vi.fn((message: ClientMessage) => { messages.push(message); return true; });
  let requestNumber = 0;
  const presentation = new BattlePresentation(surface, send, () => `request-${++requestNumber}`);
  return { surface, messages, send, presentation, display: () => display };
}

describe("battle presentation", () => {
  it("waits for artwork and an actual paint, then requires explicit ordered text advances before acknowledging", async () => {
    const h = harness();
    const artwork = deferred();
    const paint = deferred();
    h.surface.loadAssets = () => artwork.promise;
    h.surface.painted = () => paint.promise;
    const work = h.presentation.present(snapshot());
    expect(h.display().ready).toBe(false);
    await h.presentation.activate();
    expect(h.messages).toEqual([]);
    artwork.resolve();
    await Promise.resolve();
    expect(h.display().ready).toBe(false);
    paint.resolve();
    await work;
    expect(h.display().text).toBe("Rival challenges you!");
    const framePaint = deferred();
    h.surface.painted = () => framePaint.promise;
    const advance = h.presentation.activate();
    expect(h.display().frame?.player_hp).toBe(16);
    await h.presentation.activate();
    expect(h.messages).toEqual([]);
    framePaint.resolve();
    await advance;
    await h.presentation.activate();
    await h.presentation.activate();
    expect(h.messages).toEqual([{
      type: "acknowledge_battle", request_id: "request-1", battle_id: "battle-1", batch_id: "batch-1",
    }]);
  });

  it("does not replay a batch or acknowledge duplicate snapshots twice", async () => {
    const h = harness();
    await h.presentation.present(snapshot());
    await h.presentation.activate();
    await h.presentation.present(snapshot());
    expect(h.display().text).toBe("A hit!");
    await h.presentation.activate();
    await h.presentation.present(snapshot());
    await h.presentation.activate();
    expect(h.messages).toHaveLength(1);
  });

  it("shares one pending action across pointer and keyboard and ignores repeat confirmations", async () => {
    const h = harness();
    const state = { ...snapshot(), batch: null, action_token: "turn-1" };
    await h.presentation.present(state);
    expect(h.presentation.keyDown("KeyE", true)).toBe(true);
    expect(h.messages).toEqual([]);
    expect(h.presentation.keyDown("Enter")).toBe(false);
    expect(h.presentation.keyDown("Enter", true)).toBe(true);
    h.presentation.keyDown("ArrowDown");
    h.presentation.keyDown("Space");
    await h.presentation.activate(0);
    await h.presentation.present(state);
    h.presentation.keyDown("KeyE");
    expect(h.messages).toEqual([{
      type: "battle_action", request_id: "request-1", battle_id: "battle-1", action_token: "turn-1", slot: 0,
    }]);
  });

  it("retries failed artwork without acknowledging unseen frames", async () => {
    const h = harness();
    h.surface.loadAssets = vi.fn().mockRejectedValueOnce(new Error("offline")).mockResolvedValue(undefined);
    await h.presentation.present(snapshot());
    expect(h.display().error).toContain("Retry");
    await h.presentation.activate();
    expect(h.messages).toEqual([]);
    await h.presentation.retry();
    expect(h.display().ready).toBe(true);
    expect(h.display().error).toBeNull();
  });

  it("keeps a disconnected presentation disabled even if asset loading completes later", async () => {
    const h = harness();
    const artwork = deferred();
    h.surface.loadAssets = () => artwork.promise;
    const work = h.presentation.present(snapshot());
    h.presentation.unavailable();
    artwork.resolve();
    await work;
    await h.presentation.activate();
    expect(h.display().disconnected).toBe(true);
    expect(h.display().ready).toBe(false);
    expect(h.messages).toEqual([]);
  });

  it("offers Struggle only when all PP are exhausted, and never submits terminal actions", async () => {
    const h = harness();
    const state = snapshot();
    state.batch = null;
    state.action_token = "turn-1";
    state.player.moves = state.player.moves.map((move) => ({ ...move, pp: 0 }));
    await h.presentation.present(state);
    await h.presentation.activate();
    expect(h.messages[0]).toMatchObject({ type: "battle_action", slot: null });
    await h.presentation.present({ ...state, action_token: null, outcome: "player_loss" });
    expect(h.display().text).toBe("");
    await h.presentation.activate();
    expect(h.messages).toHaveLength(1);
  });

  it("handles a transport send failure without reopening input", async () => {
    const h = harness();
    h.send.mockReturnValue(false);
    await h.presentation.present({ ...snapshot(), batch: null, action_token: "turn-1" });
    await h.presentation.activate();
    expect(h.display().disconnected).toBe(true);
    await h.presentation.activate();
    expect(h.send).toHaveBeenCalledTimes(1);
  });

  it("ignores held overworld confirmation on battle entry and held Enter during text frames", async () => {
    const h = harness();
    await h.presentation.present(snapshot());
    h.presentation.keyDown("KeyE", true);
    h.presentation.keyDown("Space", true);
    expect(h.presentation.keyDown("Enter", true)).toBe(true);
    expect(h.display().text).toBe("Rival challenges you!");
    expect(h.messages).toEqual([]);
    h.presentation.keyDown("KeyE");
    await Promise.resolve();
    expect(h.display().text).toBe("A hit!");
    h.presentation.keyDown("KeyE", true);
    expect(h.messages).toEqual([]);
  });

  it("unlocks a matching blocked action response but keeps unrelated and replayed responses pending", async () => {
    const h = harness();
    const state = { ...snapshot(), batch: null, action_token: "turn-1" };
    await h.presentation.present(state);
    await h.presentation.activate();
    await h.presentation.present(state, { action: "blocked", request_id: "other-request" });
    expect(h.display().ready).toBe(false);
    await h.presentation.present(state, { action: "blocked", request_id: "request-1" });
    expect(h.display().ready).toBe(true);
    await h.presentation.activate();
    expect(h.messages).toHaveLength(2);
    await h.presentation.present(state, { action: "blocked", request_id: "request-1" });
    expect(h.display().ready).toBe(false);
  });

  it("allows an explicitly rejected presentation acknowledgement to be retried without replaying frames", async () => {
    const h = harness();
    await h.presentation.present(snapshot());
    await h.presentation.activate();
    await h.presentation.activate();
    await h.presentation.present(snapshot(), { action: "blocked", request_id: "request-1" });
    expect(h.display().text).toBe("A hit!");
    expect(h.display().ready).toBe(true);
    await h.presentation.activate();
    expect(h.messages[1]).toMatchObject({ type: "acknowledge_battle", request_id: "request-2" });
  });

  it("uses canonical terminal frames and waits for the final explicit acknowledgement", async () => {
    const h = harness();
    const state = snapshot();
    state.outcome = "player_win";
    state.batch!.frames[0]!.text = "Enemy CHARMANDER fainted!";
    state.batch!.frames[1]!.text = "RED got ¥175 for winning!";
    await h.presentation.present(state);
    expect(h.display().text).toBe("Enemy CHARMANDER fainted!");
    await h.presentation.activate();
    expect(h.display().text).toBe("RED got ¥175 for winning!");
    expect(h.messages).toEqual([]);
    await h.presentation.activate();
    await h.presentation.present(state);
    expect(h.display().ready).toBe(false);
    expect(h.messages).toHaveLength(1);
  });

  it("invalidates an in-flight paint when the battle closes and ignores stale activation", async () => {
    const h = harness();
    await h.presentation.present(snapshot());
    const paint = deferred();
    h.surface.painted = () => paint.promise;
    const advance = h.presentation.activate();
    h.presentation.close();
    const renders = vi.mocked(h.surface.render).mock.calls.length;
    paint.resolve();
    await advance;
    await h.presentation.activate();
    expect(h.surface.render).toHaveBeenCalledTimes(renders);
    expect(h.messages).toEqual([]);
  });
});
