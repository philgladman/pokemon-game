import { MOVE_DURATION_MS } from "./movement";
import type {
  ClientMessage,
  Direction,
  PresentationContext,
  StateMessage,
} from "./types";

const codeDirections: Record<string, Direction> = {
  ArrowUp: "north",
  KeyW: "north",
  ArrowDown: "south",
  KeyS: "south",
  ArrowLeft: "west",
  KeyA: "west",
  ArrowRight: "east",
  KeyD: "east",
};

const directionPriority: readonly Direction[] = ["south", "north", "west", "east"];
const interactionCodes = new Set(["KeyE", "Space"]);
export const TURN_RESAMPLE_DELAY_MS = Math.round(MOVE_DURATION_MS / 8);

export interface InputClock {
  now(): number;
  setTimer(callback: () => void, delayMs: number): number;
  clearTimer(timer: number): void;
}

const browserClock: InputClock = {
  now: () => performance.now(),
  setTimer: (callback, delayMs) => window.setTimeout(callback, delayMs),
  clearTimer: (timer) => window.clearTimeout(timer),
};

type PendingIntent =
  | { requestId: string; type: "move"; direction: Direction; continued: boolean }
  | { requestId: string; type: "interact" };
type ContinuationKind = PendingIntent["type"];

export class HeldInputController {
  private readonly heldDirectionCodes = new Set<string>();
  private readonly heldInteractionCodes = new Set<string>();
  private pending: PendingIntent | null = null;
  private continuationTimer: number | null = null;
  private continuationKind: ContinuationKind | null = null;
  private neutralTimer: number | null = null;
  private neutralRequested = false;
  private nextMoveAt = 0;
  private lastMoveWasSuccessful = false;
  private sequenceActive = false;
  private interactionQueued = false;
  private dialogOpen = false;
  private enabled = true;

  constructor(
    private readonly send: (message: ClientMessage) => boolean,
    private readonly requestId: () => string,
    private readonly clock: InputClock = browserClock,
  ) {}

  keyDown(code: string, repeated = false): boolean {
    const direction = codeDirections[code];
    if (direction !== undefined) {
      if (!this.enabled) return true;
      // A browser may continue generating repeats after blur, a dialog, or a
      // transition reset. Only a fresh physical keydown may begin a new hold.
      if (repeated && !this.heldDirectionCodes.has(code)) return true;
      if (this.heldDirectionCodes.has(code)) return true;
      const previousDirection = this.selectedDirection();
      this.heldDirectionCodes.add(code);
      const selectedDirection = this.selectedDirection();
      if (selectedDirection !== null) this.cancelPendingNeutral();
      if (this.pending === null && selectedDirection !== previousDirection) {
        this.scheduleNextIntent();
      }
      return true;
    }

    if (interactionCodes.has(code)) {
      if (!this.enabled) return true;
      if (repeated && !this.heldInteractionCodes.has(code)) return true;
      if (this.heldInteractionCodes.has(code)) return true;
      this.heldInteractionCodes.add(code);
      this.interactionQueued = true;
      if (this.pending === null) this.scheduleNextIntent();
      return true;
    }
    return false;
  }

  keyUp(code: string): boolean {
    if (codeDirections[code] !== undefined) {
      const previousDirection = this.selectedDirection();
      this.heldDirectionCodes.delete(code);
      const selectedDirection = this.selectedDirection();
      if (!this.enabled) return true;
      if (selectedDirection === null) {
        this.cancelMovementContinuation();
        this.requestNeutral();
      } else if (this.pending === null && selectedDirection !== previousDirection) {
        this.scheduleNextIntent();
      }
      return true;
    }
    if (interactionCodes.has(code)) {
      this.heldInteractionCodes.delete(code);
      return true;
    }
    return false;
  }

  handleState(message: StateMessage): PresentationContext {
    const presentation: PresentationContext = {
      resetGait:
        message.action === "connected" ||
        message.action === "transitioned" ||
        message.action === "dialog_opened" ||
        message.action === "dialog_closed",
    };
    this.dialogOpen = message.state.dialog !== null;
    if (this.dialogOpen) {
      this.clearDirectionalInput();
      this.clearQueuedInteraction();
    }

    if (this.pending === null || message.request_id !== this.pending.requestId) {
      if (presentation.resetGait) this.endSequence();
      return presentation;
    }
    const acknowledged = this.pending;
    this.pending = null;
    if (acknowledged.type === "move") {
      presentation.resetGait ||= !acknowledged.continued;
      this.lastMoveWasSuccessful =
        message.action === "moved" || message.action === "transitioned";
      if (this.lastMoveWasSuccessful) {
        // Rendering begins from this acknowledgement, so its full cadence starts here.
        this.nextMoveAt = this.clock.now() + MOVE_DURATION_MS;
      } else if (message.action === "turned") {
        this.nextMoveAt = this.clock.now() + TURN_RESAMPLE_DELAY_MS;
      } else {
        this.nextMoveAt = this.clock.now() + MOVE_DURATION_MS;
      }
      if (message.action === "transitioned") {
        this.reset();
        return presentation;
      }
      if (this.selectedDirection() === null || this.neutralRequested) {
        if (this.lastMoveWasSuccessful) this.scheduleNeutral(this.nextMoveAt);
        else this.endSequence();
      }
    }
    if (presentation.resetGait) this.endSequenceIfControlReset(message);
    this.scheduleNextIntent();
    return presentation;
  }

  setEnabled(enabled: boolean): void {
    if (this.enabled === enabled) return;
    if (!enabled) this.reset();
    this.enabled = enabled;
  }

  reset(): void {
    this.heldDirectionCodes.clear();
    this.heldInteractionCodes.clear();
    this.interactionQueued = false;
    this.pending = null;
    this.dialogOpen = false;
    this.nextMoveAt = 0;
    this.lastMoveWasSuccessful = false;
    this.sequenceActive = false;
    this.neutralRequested = false;
    this.cancelContinuation();
    this.cancelNeutralTimer();
  }

  private selectedDirection(): Direction | null {
    const heldDirections = new Set(
      [...this.heldDirectionCodes]
        .map((code) => codeDirections[code])
        .filter((direction): direction is Direction => direction !== undefined),
    );
    return directionPriority.find((direction) => heldDirections.has(direction)) ?? null;
  }

  private sendMoveImmediately(): void {
    this.cancelContinuation();
    const direction = this.selectedDirection();
    if (!this.enabled || direction === null || this.dialogOpen || this.pending !== null) return;
    const requestId = this.requestId();
    const continued = this.sequenceActive;
    if (!this.trySend({ type: "move", request_id: requestId, direction, continued })) return;
    this.sequenceActive = true;
    this.pending = { requestId, type: "move", direction, continued };
  }

  private sendInteraction(): void {
    if (!this.enabled || !this.interactionQueued || this.pending !== null) return;
    this.cancelContinuation();
    const requestId = this.requestId();
    if (!this.trySend({ type: "interact", request_id: requestId })) return;
    this.interactionQueued = false;
    this.pending = { requestId, type: "interact" };
  }

  private scheduleNextIntent(): void {
    if (this.pending !== null) return;
    if (this.interactionQueued) {
      const delay = this.lastMoveWasSuccessful
        ? Math.max(0, this.nextMoveAt - this.clock.now())
        : 0;
      this.scheduleContinuation(delay, "interact");
      return;
    }

    const direction = this.selectedDirection();
    if (!this.enabled || direction === null || this.dialogOpen) return;
    const delay = Math.max(0, this.nextMoveAt - this.clock.now());
    this.scheduleContinuation(delay, "move");
  }

  private scheduleContinuation(delay: number, kind: ContinuationKind): void {
    if (delay === 0) {
      if (this.interactionQueued) this.sendInteraction();
      else this.sendMoveImmediately();
      return;
    }
    this.cancelContinuation();
    this.continuationKind = kind;
    this.continuationTimer = this.clock.setTimer(() => {
      this.continuationTimer = null;
      this.continuationKind = null;
      this.scheduleNextIntent();
    }, delay);
  }

  private trySend(message: ClientMessage): boolean {
    try {
      if (this.send(message)) return true;
    } catch {
      // A failed transport invalidates held input; a fresh key press can retry.
    }
    this.reset();
    return false;
  }

  private cancelContinuation(): void {
    if (this.continuationTimer === null) return;
    this.clock.clearTimer(this.continuationTimer);
    this.continuationTimer = null;
    this.continuationKind = null;
  }

  private clearDirectionalInput(): void {
    this.heldDirectionCodes.clear();
    this.cancelMovementContinuation();
    this.endSequence();
  }

  private cancelMovementContinuation(): void {
    if (this.continuationKind === "move") this.cancelContinuation();
  }

  private clearQueuedInteraction(): void {
    this.heldInteractionCodes.clear();
    this.interactionQueued = false;
    if (this.continuationKind === "interact") this.cancelContinuation();
  }

  private requestNeutral(): void {
    this.neutralRequested = true;
    if (this.pending?.type === "move") return;
    if (this.lastMoveWasSuccessful && this.clock.now() < this.nextMoveAt) {
      this.scheduleNeutral(this.nextMoveAt);
      return;
    }
    this.endSequence();
  }

  private scheduleNeutral(deadline: number): void {
    this.cancelNeutralTimer();
    const delay = Math.max(0, deadline - this.clock.now());
    if (delay === 0) {
      this.endSequence();
      return;
    }
    this.neutralTimer = this.clock.setTimer(() => {
      this.neutralTimer = null;
      if (this.selectedDirection() === null) this.endSequence();
    }, delay);
  }

  private cancelPendingNeutral(): void {
    this.neutralRequested = false;
    this.cancelNeutralTimer();
  }

  private cancelNeutralTimer(): void {
    if (this.neutralTimer === null) return;
    this.clock.clearTimer(this.neutralTimer);
    this.neutralTimer = null;
  }

  private endSequence(): void {
    this.sequenceActive = false;
    this.neutralRequested = false;
    this.nextMoveAt = 0;
    this.lastMoveWasSuccessful = false;
    this.cancelNeutralTimer();
  }

  private endSequenceIfControlReset(message: StateMessage): void {
    if (
      message.action === "transitioned" ||
      message.action === "dialog_opened" ||
      message.action === "dialog_closed"
    ) {
      this.endSequence();
    }
  }
}

