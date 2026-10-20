import type { GameRenderer, PresentationContext, StateMessage } from "./types";

export const FADE_STAGE_MS = 134;
export const FADE_STAGES = 4;

export interface TransitionOverlay {
  hidden: boolean;
  style: { opacity: string };
}

export type TransitionWait = (milliseconds: number) => Promise<void>;

export interface PresentationAcknowledgements {
  movementCue?: (message: StateMessage) => boolean;
  transition?: (message: StateMessage) => boolean;
}

const browserWait: TransitionWait = (milliseconds) =>
  new Promise((resolve) => window.setTimeout(resolve, milliseconds));

export class TransitionCoordinator {
  private sequence: Promise<void> = Promise.resolve();
  private awaitingTransitionResponse = false;
  private pendingTransitionRetry: {
    message: StateMessage;
    presentation: PresentationContext;
  } | null = null;
  private retryInFlight = false;

  constructor(
    private readonly renderer: GameRenderer,
    private readonly overlay: TransitionOverlay,
    private readonly setInputEnabled: (enabled: boolean) => void,
    private readonly applyInterface: (message: StateMessage) => void,
    private readonly reportError: (error: unknown) => void,
    private readonly wait: TransitionWait = browserWait,
    private readonly acknowledgements: PresentationAcknowledgements = {},
  ) {}

  present(message: StateMessage, presentation: PresentationContext): Promise<void> {
    if (message.action === "transitioned") this.setInputEnabled(false);
    const work = this.sequence.then(() => this.presentNext(message, presentation));
    this.sequence = work.catch(() => undefined);
    return work;
  }

  hasPendingRetry(): boolean {
    return this.pendingTransitionRetry !== null;
  }

  async retryPending(): Promise<boolean> {
    const pending = this.pendingTransitionRetry;
    if (pending === null || this.retryInFlight) return false;
    this.retryInFlight = true;
    try {
      await this.present(pending.message, pending.presentation);
    } finally {
      this.retryInFlight = false;
    }
    return true;
  }

  private async presentNext(
    message: StateMessage,
    presentation: PresentationContext,
  ): Promise<void> {
    if (message.action !== "transitioned") {
      const completesTransition =
        this.awaitingTransitionResponse && message.state.transition === null;
      const presentsMovementCue = message.state.movement_cue !== null;
      try {
        if (presentsMovementCue) this.applyInterface(message);
        await this.renderer.update(message.state, presentation);
        if (!presentsMovementCue) this.applyInterface(message);
        if (presentsMovementCue) this.acknowledgements.movementCue?.(message);
      } catch (error: unknown) {
        this.reportError(error);
      } finally {
        if (completesTransition) {
          this.awaitingTransitionResponse = false;
          this.setInputEnabled(true);
        }
      }
      return;
    }

    this.overlay.hidden = false;
    this.awaitingTransitionResponse = message.state.transition !== null;
    this.overlay.style.opacity = "0";
    let presented = false;
    try {
      for (let stage = 1; stage <= FADE_STAGES; stage += 1) {
        this.overlay.style.opacity = String(stage / FADE_STAGES);
        await this.wait(FADE_STAGE_MS);
      }
      await this.renderer.update(message.state, presentation);
      this.applyInterface(message);
      for (let stage = FADE_STAGES - 1; stage >= 0; stage -= 1) {
        this.overlay.style.opacity = String(stage / FADE_STAGES);
        await this.wait(FADE_STAGE_MS);
      }
      presented = true;
    } catch (error: unknown) {
      if (this.awaitingTransitionResponse) {
        this.pendingTransitionRetry = { message, presentation };
      }
      this.reportError(error);
    } finally {
      this.overlay.style.opacity = "0";
      this.overlay.hidden = true;
      if (presented) {
        const acknowledged = this.acknowledgements.transition?.(message) ?? false;
        if (!this.awaitingTransitionResponse || acknowledged) {
          this.pendingTransitionRetry = null;
        } else {
          this.pendingTransitionRetry = { message, presentation };
          this.reportError(new Error("Unable to acknowledge the rendered transition"));
        }
      }
      if (!this.awaitingTransitionResponse) {
        this.setInputEnabled(true);
      }
    }
  }
}
