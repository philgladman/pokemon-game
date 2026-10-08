import type { ClientMessage, ServerMessage, StateMessage } from "./types";

type StateHandler = (message: StateMessage) => void;
type StatusHandler = (status: string) => void;

export function shouldAcceptState(currentVersion: number, incomingVersion: number): boolean {
  return incomingVersion >= currentVersion;
}

export class GameClient {
  private socket: WebSocket | null = null;
  private stateVersion = -1;

  constructor(
    private readonly onState: StateHandler,
    private readonly onStatus: StatusHandler,
  ) {}

  connect(): void {
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    this.socket = new WebSocket(`${scheme}://${window.location.host}/ws/game`);
    this.socket.addEventListener("open", () => this.onStatus("Connected"));
    this.socket.addEventListener("close", () => this.onStatus("Disconnected — refresh to reconnect"));
    this.socket.addEventListener("error", () => this.onStatus("Connection error"));
    this.socket.addEventListener("message", (event: MessageEvent<string>) => {
      const message = JSON.parse(event.data) as ServerMessage;
      if (message.type === "error") {
        this.onStatus(message.message);
        return;
      }
      if (!shouldAcceptState(this.stateVersion, message.state_version)) {
        return;
      }
      this.stateVersion = message.state_version;
      this.onState(message);
    });
  }

  send(message: ClientMessage): boolean {
    if (this.socket?.readyState !== WebSocket.OPEN) {
      return false;
    }
    this.socket.send(JSON.stringify(message));
    return true;
  }
}
