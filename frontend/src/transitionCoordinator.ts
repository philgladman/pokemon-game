import type { GameRenderer, PresentationContext, StateMessage } from "./types";

export const FADE_STAGE_MS = 134;
export const FADE_STAGES = 4;

export interface TransitionOverlay {
  hidden: boolean;
  style: { opacity: string };
}

export type TransitionWait = (milliseconds: number) => Promise<void>;

const browserWait: TransitionWait = (milliseconds) =>
  new Promise((resolve) => window.setTimeout(resolve, milliseconds));

export class TransitionCoordinator {
  private sequence: Promise<void> = Promise.resolve();

  constructor(
    private readonly renderer: GameRenderer,
    private readonly overlay: TransitionOverlay,
    private readonly setInputEnabled: (enabled: boolean) => void,
    private readonly applyInterface: (message: StateMessage) => void,
    private readonly reportError: (error: unknown) => void,
    private readonly wait: TransitionWait = browserWait,
  ) {}

  present(message: StateMessage, presentation: PresentationContext): Promise<void> {
    if (message.action === "transitioned") this.setInputEnabled(false);
    const work = this.sequence.then(() => this.presentNext(message, presentation));
    this.sequence = work.catch(() => undefined);
    return work;
  }

  private async presentNext(
    message: StateMessage,
    presentation: PresentationContext,
  ): Promise<void> {
    if (message.action !== "transitioned") {
      try {
        await this.renderer.update(message.state, presentation);
        this.applyInterface(message);
      } catch (error: unknown) {
        this.reportError(error);
      }
      return;
    }

    this.overlay.hidden = false;
    this.overlay.style.opacity = "0";
    try {
      for (let stage = 1; stage <= FADE_STAGES; stage += 1) {
        this.overlay.style.opacity = String(stage / FADE_STAGES);
        await this.wait(FADE_STAGE_MS);
      }
      try {
        await this.renderer.update(message.state, presentation);
        this.applyInterface(message);
      } catch (error: unknown) {
        this.reportError(error);
      }
      for (let stage = FADE_STAGES - 1; stage >= 0; stage -= 1) {
        this.overlay.style.opacity = String(stage / FADE_STAGES);
        await this.wait(FADE_STAGE_MS);
      }
    } catch (error: unknown) {
      this.reportError(error);
    } finally {
      this.overlay.style.opacity = "0";
      this.overlay.hidden = true;
      this.setInputEnabled(true);
    }
  }
}
