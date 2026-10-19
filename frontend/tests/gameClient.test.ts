import { afterEach, describe, expect, it, vi } from "vitest";

import { GameClient, shouldAcceptState } from "../src/gameClient";

class FakeWebSocket {
  static readonly OPEN = 1;
  readyState = FakeWebSocket.OPEN;
  private readonly listeners = new Map<string, Array<(event: unknown) => void>>();

  addEventListener(type: string, listener: (event: unknown) => void): void {
    const listeners = this.listeners.get(type) ?? [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }

  send(): void {}

  emit(type: string, event: unknown = {}): void {
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("shouldAcceptState", () => {
  it("rejects stale server snapshots", () => {
    expect(shouldAcceptState(8, 7)).toBe(false);
  });

  it("accepts current and newer server snapshots", () => {
    expect(shouldAcceptState(8, 8)).toBe(true);
    expect(shouldAcceptState(8, 9)).toBe(true);
  });
});

describe("GameClient transport lifecycle", () => {
  it("reports disconnects, socket errors, and protocol errors as unavailable", () => {
    vi.stubGlobal("window", { location: { protocol: "http:", host: "example.test" } });
    vi.stubGlobal("WebSocket", FakeWebSocket);
    const unavailable = vi.fn();
    const statuses: string[] = [];
    const client = new GameClient(
      () => undefined,
      (status) => statuses.push(status),
      unavailable,
    );
    client.connect();
    const socket = (client as unknown as { socket: FakeWebSocket }).socket;

    socket.emit("error");
    socket.emit("close");
    socket.emit("message", {
      data: JSON.stringify({
        type: "error",
        request_id: "request-1",
        code: "invalid_message",
        message: "Bad message",
      }),
    });

    expect(unavailable).toHaveBeenCalledTimes(3);
    expect(statuses).toEqual([
      "Connection error",
      "Disconnected — refresh to reconnect",
      "Bad message",
    ]);
  });

  it("clears input state when a server frame is malformed", () => {
    vi.stubGlobal("window", { location: { protocol: "http:", host: "example.test" } });
    vi.stubGlobal("WebSocket", FakeWebSocket);
    const unavailable = vi.fn();
    const status = vi.fn();
    const client = new GameClient(() => undefined, status, unavailable);
    client.connect();
    const socket = (client as unknown as { socket: FakeWebSocket }).socket;

    socket.emit("message", { data: "not-json" });

    expect(unavailable).toHaveBeenCalledOnce();
    expect(status).toHaveBeenLastCalledWith("Invalid server message");
  });
});

