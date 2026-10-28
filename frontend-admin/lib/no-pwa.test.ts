import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * L'administration n'est PAS une application installable (prompt 29, ADR 0102) : outil
 * d'équipe, aucun cache sur des appareils personnels. Ni manifeste, ni service worker.
 */
const ROOT = join(__dirname, "..");

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.(tsx?|js)$/.test(name) && !/\.test\.tsx?$/.test(name) ? [path] : [];
  });
}

describe("administration sans PWA (ADR 0102)", () => {
  it("n'a ni manifeste ni service worker", () => {
    for (const path of [
      "app/manifest.ts",
      "app/manifest.json",
      "app/manifest.webmanifest",
      "app/sw.js",
      "public/sw.js",
      "public/manifest.webmanifest",
    ]) {
      expect(existsSync(join(ROOT, path)), path).toBe(false);
    }
  });

  it("n'enregistre aucun service worker", () => {
    const offenders = ["app", "components", "lib"]
      .flatMap((dir) => sources(join(ROOT, dir)))
      .filter((file) => /serviceWorker|beforeinstallprompt/.test(readFileSync(file, "utf8")));
    expect(offenders).toEqual([]);
  });
});
