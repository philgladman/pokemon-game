import { describe, expect, it } from "vitest";
import type { UserConfig } from "vite";

import config from "../vite.config";

describe("development asset routing", () => {
  it("proxies allowlisted source assets to FastAPI", () => {
    const userConfig = config as UserConfig;

    expect(userConfig.server?.proxy?.["/source-assets"]).toBe("http://localhost:8000");
  });

  it("reserves a distinct namespace for generated frontend bundles", () => {
    const userConfig = config as UserConfig;

    expect(userConfig.build?.assetsDir).toBe("frontend");
  });
});
