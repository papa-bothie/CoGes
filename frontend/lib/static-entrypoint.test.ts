import { execFileSync } from "node:child_process";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  utimesSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * Fichiers statiques gardés d'un déploiement à l'autre (ADR 0102) : `static-entrypoint.sh`
 * ajoute ceux de la nouvelle image au volume sans toucher aux anciens, et retire ceux qui ont
 * plus de 14 jours. Un écran resté ouvert sur l'ancienne version charge encore ses fichiers.
 */
const SCRIPT = join(__dirname, "..", "static-entrypoint.sh");

function deploy(root: string, files: Record<string, string>) {
  for (const [path, content] of Object.entries(files)) {
    const full = join(root, "static-build", path);
    mkdirSync(join(full, ".."), { recursive: true });
    writeFileSync(full, content);
  }
  execFileSync("sh", [SCRIPT, "true"], { env: { ...process.env, STATIC_ROOT: root } });
}

describe("fichiers des builds précédents (ADR 0102)", () => {
  it("garde l'ancien build après un déploiement, puis l'oublie après 14 jours", () => {
    const first = mkdtempSync(join(tmpdir(), "coges-static-"));
    deploy(first, { "chunks/old-a1.js": "ancien" });
    const served = join(first, ".next", "static");
    expect(readFileSync(join(served, "chunks/old-a1.js"), "utf8")).toBe("ancien");

    // Nouveau déploiement : nouvelle image, même volume.
    const next = join(first, "static-build");
    execFileSync("rm", ["-rf", next]);
    deploy(first, { "chunks/new-b2.js": "nouveau" });
    expect(existsSync(join(served, "chunks/old-a1.js"))).toBe(true);
    expect(existsSync(join(served, "chunks/new-b2.js"))).toBe(true);

    // 15 jours plus tard, au redémarrage : l'ancien part, celui de l'image reste.
    const old = Date.now() / 1000 - 15 * 24 * 3600;
    utimesSync(join(served, "chunks/old-a1.js"), old, old);
    utimesSync(join(served, "chunks/new-b2.js"), old, old);
    execFileSync("sh", [SCRIPT, "true"], { env: { ...process.env, STATIC_ROOT: first } });
    expect(existsSync(join(served, "chunks/old-a1.js"))).toBe(false);
    expect(existsSync(join(served, "chunks/new-b2.js"))).toBe(true);
  });
});
