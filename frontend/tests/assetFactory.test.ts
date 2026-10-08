import * as THREE from "three";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AssetFactory, requireAppearance } from "../src/assetFactory";
import type { AppearanceDefinition, PrimitiveAsset } from "../src/types";

const primitiveTree: PrimitiveAsset = {
  type: "primitive",
  shape: "tree",
  color: "#006600",
  secondary_color: "#553311",
  scale: [1, 1, 1],
};
const appearance: AppearanceDefinition = {
  id: "tile.tree",
  base_color: "#00aa00",
  source: primitiveTree,
};

describe("requireAppearance", () => {
  it("resolves a gameplay appearance reference through the manifest", () => {
    expect(requireAppearance({ "tile.tree": appearance }, "tile.tree")).toBe(appearance);
  });

  it("fails clearly for an unknown appearance", () => {
    expect(() => requireAppearance({}, "tile.missing")).toThrow("Unknown appearance tile.missing");
  });
});

describe("AssetFactory", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("preserves the primitive fallback when a GLB fails to load", async () => {
    const warning = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const factory = new AssetFactory(async () => {
      throw new Error("fixture load failure");
    });
    const root = factory.create({
      id: "tile.future_tree",
      base_color: "#00aa00",
      source: {
        type: "gltf",
        url: "/assets/models/future-tree.glb",
        scale: [1, 1, 1],
        fallback: primitiveTree,
      },
    });
    await vi.waitFor(() => expect(warning).toHaveBeenCalledOnce());

    const sourceGroup = root.children[1];
    expect(sourceGroup).toBeInstanceOf(THREE.Group);
    expect(sourceGroup?.children).toHaveLength(1);
    expect(sourceGroup?.children[0]).toBeInstanceOf(THREE.Group);
  });
});
