import { readFile, readdir, rm, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { build } from "vite";

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const outputDirectory = join(tmpdir(), `pokemon-game-frontend-${process.pid}`);

let bundleUrls: string[] = [];

beforeAll(async () => {
  await build({
    root: projectRoot,
    configFile: resolve(projectRoot, "vite.config.ts"),
    logLevel: "silent",
    build: {
      outDir: outputDirectory,
      emptyOutDir: true,
    },
  });

  const index = await readFile(join(outputDirectory, "index.html"), "utf8");
  bundleUrls = [...index.matchAll(/(?:src|href)="([^"]+\.(?:js|css))"/g)].map(
    (match) => match[1]!,
  );
});

afterAll(async () => {
  await rm(outputDirectory, { recursive: true, force: true });
});

describe("production bundle routing", () => {
  it("keeps generated bundles out of the backend-owned gameplay asset namespace", async () => {
    expect(bundleUrls.length).toBeGreaterThan(0);
    expect(bundleUrls.every((url) => url.startsWith("/frontend/"))).toBe(true);
    expect(bundleUrls.every((url) => !url.startsWith("/assets/"))).toBe(true);

    const generatedBundleNames = await readdir(join(outputDirectory, "frontend"));
    expect(generatedBundleNames.length).toBeGreaterThan(0);

    for (const url of bundleUrls) {
      const bundle = await stat(join(outputDirectory, url.slice(1)));
      expect(bundle.size).toBeGreaterThan(0);
    }
  });
});
