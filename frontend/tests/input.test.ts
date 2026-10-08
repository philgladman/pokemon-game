import { describe, expect, it } from "vitest";

import { messageForKey } from "../src/input";

describe("messageForKey", () => {
  it.each([
    ["w", "north"],
    ["ArrowDown", "south"],
    ["a", "west"],
    ["D", "east"],
  ])("maps %s to a server movement intent", (key, direction) => {
    expect(messageForKey(key, "request-1")).toEqual({
      type: "move",
      request_id: "request-1",
      direction,
    });
  });

  it("maps interaction keys and ignores unrelated input", () => {
    expect(messageForKey(" ", "request-2")).toEqual({
      type: "interact",
      request_id: "request-2",
    });
    expect(messageForKey("q", "request-3")).toBeNull();
  });
});

