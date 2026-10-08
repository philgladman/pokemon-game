import { describe, expect, it } from "vitest";

import { shouldAcceptState } from "../src/gameClient";

describe("shouldAcceptState", () => {
  it("rejects stale server snapshots", () => {
    expect(shouldAcceptState(8, 7)).toBe(false);
  });

  it("accepts current and newer server snapshots", () => {
    expect(shouldAcceptState(8, 8)).toBe(true);
    expect(shouldAcceptState(8, 9)).toBe(true);
  });
});

