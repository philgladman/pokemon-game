import type { ClientMessage, SessionSnapshot } from "./types";

export class CueAcknowledger {
  private readonly acknowledged = new Set<string>();

  constructor(
    private readonly send: (message: ClientMessage) => boolean,
    private readonly requestId: () => string,
  ) {}

  rendered(snapshot: SessionSnapshot): boolean {
    const cue = snapshot.movement_cue;
    if (cue === null || this.acknowledged.has(cue.id)) return false;
    const sent = this.send({
      type: "acknowledge_cue",
      request_id: this.requestId(),
      cue_id: cue.id,
    });
    if (sent) this.acknowledged.add(cue.id);
    return sent;
  }

  reset(): void {
    this.acknowledged.clear();
  }
}
