import type { ClientMessage, Direction } from "./types";

const directions: Record<string, Direction> = {
  ArrowUp: "north",
  w: "north",
  W: "north",
  ArrowDown: "south",
  s: "south",
  S: "south",
  ArrowLeft: "west",
  a: "west",
  A: "west",
  ArrowRight: "east",
  d: "east",
  D: "east",
};

export function messageForKey(key: string, requestId: string): ClientMessage | null {
  const direction = directions[key];
  if (direction !== undefined) {
    return { type: "move", request_id: requestId, direction };
  }
  if (key === "e" || key === "E" || key === " ") {
    return { type: "interact", request_id: requestId };
  }
  return null;
}

