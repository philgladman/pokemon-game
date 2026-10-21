import type { BattleFrame, BattleSnapshot, ClientMessage, StateMessage } from "./types";

export interface BattleDisplay {
  battle: BattleSnapshot;
  frame: BattleFrame | null;
  text: string;
  ready: boolean;
  selected: number;
  error: string | null;
  disconnected: boolean;
}

export interface BattleSurface {
  loadAssets(battle: BattleSnapshot): Promise<void>;
  render(display: BattleDisplay): void;
  painted(): Promise<void>;
}

const battleKeys = new Set([
  "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight",
  "KeyW", "KeyS", "KeyA", "KeyD", "KeyE", "Space",
]);

export class BattlePresentation {
  private battle: BattleSnapshot | null = null;
  private frameIndex = 0;
  private selected = 0;
  private ready = false;
  private pending = false;
  private pendingRequestId: string | null = null;
  private disconnected = false;
  private error: string | null = null;
  private generation = 0;
  private lastAcknowledgedBatch: string | null = null;

  constructor(
    private readonly surface: BattleSurface,
    private readonly send: (message: ClientMessage) => boolean,
    private readonly requestId: () => string,
  ) {}

  async present(battle: BattleSnapshot, response?: Pick<StateMessage, "request_id" | "action">): Promise<void> {
    // Replayed snapshots must not restart text or unlock a submitted action.
    if (this.battle?.id === battle.id && this.battle.batch?.id === battle.batch?.id
      && this.battle.action_token === battle.action_token) {
      if (response?.action === "blocked" && response.request_id === this.pendingRequestId
        && this.pending && !this.disconnected) {
        this.pending = false;
        this.pendingRequestId = null;
        if (this.lastAcknowledgedBatch === this.batchKey(battle)) this.lastAcknowledgedBatch = null;
        this.ready = true;
        this.draw();
      }
      return;
    }
    this.battle = battle;
    this.frameIndex = 0;
    this.selected = 0;
    this.pending = false;
    this.pendingRequestId = null;
    this.error = null;
    await this.prepare();
  }

  async retry(): Promise<void> {
    if (this.error === null || this.disconnected) return;
    this.error = null;
    await this.prepare();
  }

  unavailable(): void {
    this.generation += 1;
    this.disconnected = true;
    this.ready = false;
    this.draw();
  }

  close(): void {
    this.generation += 1;
    this.battle = null;
    this.ready = false;
    this.pending = false;
    this.pendingRequestId = null;
    this.lastAcknowledgedBatch = null;
    this.error = null;
  }

  keyDown(code: string, repeated = false): boolean {
    if (code === "Enter") return repeated;
    if (!battleKeys.has(code)) return false;
    if (repeated || !this.ready) return true;
    if (code === "KeyE" || code === "Space") {
      void this.activate();
      return true;
    }
    const moves = this.availableSlots();
    if (moves.length > 0) {
      const offset = ["ArrowUp", "ArrowLeft", "KeyW", "KeyA"].includes(code) ? -1 : 1;
      this.selected = (this.selected + offset + moves.length) % moves.length;
      this.draw();
    }
    return true;
  }

  async activate(slot?: number | null): Promise<void> {
    const battle = this.battle;
    if (battle === null || !this.ready || this.pending || this.disconnected) return;
    if (battle.batch !== null && this.lastAcknowledgedBatch !== this.batchKey(battle)) {
      this.ready = false;
      if (this.frameIndex + 1 < battle.batch.frames.length) {
        this.frameIndex += 1;
        this.draw();
        const generation = this.generation;
        await this.surface.painted();
        if (generation !== this.generation) return;
        this.ready = true;
        this.draw();
        return;
      }
      this.pending = true;
      this.pendingRequestId = this.requestId();
      this.draw();
      const sent = this.trySend({
        type: "acknowledge_battle", request_id: this.pendingRequestId,
        battle_id: battle.id, batch_id: battle.batch.id,
      });
      if (sent) this.lastAcknowledgedBatch = this.batchKey(battle);
      return;
    }
    if (battle.action_token === null) return;
    const slots = this.availableSlots();
    const chosen = slot === undefined ? slots[this.selected] : slot;
    if (chosen === undefined || !slots.includes(chosen)) return;
    this.pending = true;
    this.pendingRequestId = this.requestId();
    this.ready = false;
    this.draw();
    this.trySend({
      type: "battle_action", request_id: this.pendingRequestId, battle_id: battle.id,
      action_token: battle.action_token, slot: chosen,
    });
  }

  private availableSlots(): (number | null)[] {
    const moves = this.battle?.player.moves.filter((move) => move.pp > 0) ?? [];
    return moves.length === 0 ? [null] : moves.map((move) => move.slot);
  }

  private async prepare(): Promise<void> {
    const battle = this.battle;
    if (battle === null || this.disconnected) return;
    const generation = ++this.generation;
    this.ready = false;
    this.draw();
    try {
      await this.surface.loadAssets(battle);
      if (generation !== this.generation) return;
      this.draw();
      await this.surface.painted();
      if (generation !== this.generation) return;
      this.ready = true;
      this.draw();
    } catch {
      if (generation !== this.generation) return;
      this.error = "Unable to load battle artwork. Retry to continue.";
      this.draw();
    }
  }

  private trySend(message: ClientMessage): boolean {
    try {
      if (this.send(message)) return true;
    } catch { /* The transport may close between the ready check and send. */ }
    this.unavailable();
    return false;
  }

  private batchKey(battle: BattleSnapshot): string {
    return `${battle.id}:${battle.batch?.id}`;
  }

  private draw(): void {
    const battle = this.battle;
    if (battle === null) return;
    const frame = battle.batch?.frames[this.frameIndex] ?? null;
    this.surface.render({
      battle, frame, ready: this.ready && !this.pending, selected: this.selected,
      error: this.error, disconnected: this.disconnected,
      text: frame?.text ?? (battle.action_token === null ? "" : "Choose a move."),
    });
  }
}
