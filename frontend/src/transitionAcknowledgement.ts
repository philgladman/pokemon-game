import type { ClientMessage, SessionSnapshot } from "./types";

export class TransitionAcknowledger {
  private readonly acknowledged = new Set<string>();

  constructor(
    private readonly send: (message: ClientMessage) => boolean,
    private readonly requestId: () => string,
  ) {}

  rendered(snapshot: SessionSnapshot): boolean {
    const transition = snapshot.transition;
    if (transition === null || this.acknowledged.has(transition.id)) return false;
    const sent = this.send({
      type: "acknowledge_transition",
      request_id: this.requestId(),
      transition_id: transition.id,
    });
    if (sent) this.acknowledged.add(transition.id);
    return sent;
  }

  reset(): void {
    this.acknowledged.clear();
  }
}
