import { afterEach, describe, expect, it, vi } from "vitest";

import { ThreeDResourceLoader } from "../src/renderers/three_d/resources";
import {
  PlayerMotionAuthority,
  WorldRenderer,
} from "../src/renderers/three_d/WorldRenderer";
import type { GameRenderer } from "../src/types";

describe("ThreeDResourceLoader", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("loads the manifest separately and caches resources by map", async () => {
    const fetchMock = vi.fn(async (url: string) => ({
      ok: true,
      json: async () =>
        url.endsWith("/manifest")
          ? { "character.player": { id: "character.player" } }
          : { map_id: "PALLET_TOWN" },
    }));
    vi.stubGlobal("fetch", fetchMock);
    const loader = new ThreeDResourceLoader();

    await Promise.all([
      loader.manifest(),
      loader.manifest(),
      loader.map("PALLET_TOWN"),
      loader.map("PALLET_TOWN"),
    ]);

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock).toHaveBeenCalledWith("/api/renderers/three-d/manifest");
    expect(fetchMock).toHaveBeenCalledWith("/api/renderers/three-d/maps/PALLET_TOWN");
  });

  it("drops failed requests so they can be retried", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: false })
      .mockResolvedValueOnce({ ok: true, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchMock);
    const loader = new ThreeDResourceLoader();

    await expect(loader.manifest()).rejects.toThrow("Unable to load renderer resource");
    await expect(loader.manifest()).resolves.toEqual({});
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("keeps the 3D adapter on the asynchronous renderer contract", () => {
    const update: GameRenderer["update"] = WorldRenderer.prototype.update;

    expect(update.constructor.name).toBe("AsyncFunction");
  });

  it("gives scripted player motion authority through the acknowledgement roundtrip", () => {
    const authority = new PlayerMotionAuthority();

    authority.observeSnapshot(true);
    expect(authority.normalInterpolationAllowed()).toBe(false);
    authority.snapshotApplied(true);
    authority.observeSnapshot(false);
    expect(authority.normalInterpolationAllowed()).toBe(false);
    authority.snapshotApplied(false);
    expect(authority.normalInterpolationAllowed()).toBe(true);
  });
});
