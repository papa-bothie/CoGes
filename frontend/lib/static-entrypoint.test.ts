import { execFileSync, spawnSync } from "node:child_process";
import {
  chmodSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
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
    const later = Math.floor(Date.now() / 1000) + 15 * 24 * 3600;
    execFileSync("sh", [SCRIPT, "true"], {
      env: { ...process.env, STATIC_ROOT: first, STATIC_NOW: String(later) },
    });
    expect(existsSync(join(served, "chunks/old-a1.js"))).toBe(false);
    expect(existsSync(join(served, "chunks/new-b2.js"))).toBe(true);
  });

  it("ne fait jamais échouer le démarrage, et sans avertissement de cp", () => {
    const root = mkdtempSync(join(tmpdir(), "coges-static-"));
    deploy(root, { "chunks/a1.js": "a" });
    // Volume en lecture seule : la copie et le nettoyage échouent, le front démarre quand même.
    const served = join(root, ".next", "static");
    chmodSync(join(served, "chunks"), 0o555);
    mkdirSync(join(root, "static-build", "chunks"), { recursive: true });
    writeFileSync(join(root, "static-build", "chunks", "b2.js"), "b");
    const marker = join(root, "started");
    const run = spawnSync("sh", [SCRIPT, "sh", "-c", `echo ok > ${marker}`], {
      env: { ...process.env, STATIC_ROOT: root },
      encoding: "utf8",
    });
    chmodSync(join(served, "chunks"), 0o755);
    expect(run.status).toBe(0);
    expect(readFileSync(marker, "utf8").trim()).toBe("ok");
    expect(run.stderr).not.toMatch(/non-portable/);
  });
});

const DAY = 24 * 3600;
// Dans le passé : l'ancien script comparait les dates des fichiers à l'heure réelle.
const T0 = Math.floor(Date.now() / 1000) - 60 * DAY;

/** Démarrage d'une image à la date `at` (secondes) : ses fichiers ont la date du build. */
function start(root: string, files: Record<string, string>, at: number) {
  rmSync(join(root, "static-build"), { recursive: true, force: true });
  for (const [path, content] of Object.entries(files)) {
    const full = join(root, "static-build", path);
    mkdirSync(join(full, ".."), { recursive: true });
    writeFileSync(full, content);
  }
  execFileSync("sh", [SCRIPT, "true"], {
    env: { ...process.env, STATIC_ROOT: root, STATIC_NOW: String(at) },
  });
  // Le disque vieillit avec l'horloge (l'ancien script ne lit que les dates des fichiers).
  execFileSync("find", [
    join(root, ".next", "static"),
    "-type",
    "f",
    "-exec",
    "touch",
    "-d",
    `@${at}`,
    "{}",
    "+",
  ]);
}

describe("14 jours après la fin d'un build (prompt 32, P1)", () => {
  const served = (root: string, path: string) => existsSync(join(root, ".next", "static", path));

  it("deux déploiements espacés de 20 jours : l'ancien reste 14 jours après le nouveau", () => {
    const root = mkdtempSync(join(tmpdir(), "coges-static-"));
    start(root, { "chunks/old-a1.js": "a" }, T0);
    start(root, { "chunks/new-b2.js": "b" }, T0 + 20 * DAY);
    expect(served(root, "chunks/old-a1.js")).toBe(true);
    start(root, { "chunks/new-b2.js": "b" }, T0 + 20 * DAY + 14 * DAY - 60);
    expect(served(root, "chunks/old-a1.js")).toBe(true);
    start(root, { "chunks/new-b2.js": "b" }, T0 + 20 * DAY + 14 * DAY + 60);
    expect(served(root, "chunks/old-a1.js")).toBe(false);
    expect(served(root, "chunks/new-b2.js")).toBe(true);
  });

  it("deux déploiements le même jour : chacun garde ses 14 jours", () => {
    const root = mkdtempSync(join(tmpdir(), "coges-static-"));
    start(root, { "chunks/a.js": "a", "chunks/shared.js": "s" }, T0);
    start(root, { "chunks/b.js": "b", "chunks/shared.js": "s" }, T0 + 3600);
    start(root, { "chunks/c.js": "c" }, T0 + 7200);
    expect(served(root, "chunks/a.js")).toBe(true);
    expect(served(root, "chunks/b.js")).toBe(true);
    // A cesse d'être courant à T0 + 1 h, B à T0 + 2 h : 14 jours après, A part, B reste.
    start(root, { "chunks/c.js": "c" }, T0 + 3600 + 14 * DAY + 60);
    expect(served(root, "chunks/a.js")).toBe(false);
    expect(served(root, "chunks/b.js")).toBe(true);
    expect(served(root, "chunks/shared.js")).toBe(true);
    start(root, { "chunks/c.js": "c" }, T0 + 7200 + 14 * DAY + 60);
    expect(served(root, "chunks/a.js")).toBe(false);
    expect(served(root, "chunks/b.js")).toBe(false);
    expect(served(root, "chunks/shared.js")).toBe(false);
    expect(served(root, "chunks/c.js")).toBe(true);
  });

  it("un fichier commun à l'ancien et au nouveau build n'est jamais retiré", () => {
    const root = mkdtempSync(join(tmpdir(), "coges-static-"));
    start(root, { "chunks/a.js": "a", "media/font.woff2": "f" }, T0);
    start(root, { "chunks/b.js": "b", "media/font.woff2": "f" }, T0 + DAY);
    start(root, { "chunks/b.js": "b", "media/font.woff2": "f" }, T0 + 40 * DAY);
    expect(served(root, "chunks/a.js")).toBe(false);
    expect(served(root, "media/font.woff2")).toBe(true);
  });

  it("volume neuf : les fichiers de l'image sont servis tout de suite", () => {
    const root = mkdtempSync(join(tmpdir(), "coges-static-"));
    start(root, { "chunks/a.js": "a" }, T0);
    expect(readFileSync(join(root, ".next", "static", "chunks", "a.js"), "utf8")).toBe("a");
  });
});
