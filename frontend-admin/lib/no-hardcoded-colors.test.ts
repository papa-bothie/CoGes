import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * Règle 2 de la maquette v2 (ADR 0064), reprise par l'administration (ADR 0094) : toute couleur vient du thème (`app/globals.css`,
 * repris de `docs/design/maquette-v2/tokens.css`). Aucune valeur en dur dans `app/` ni
 * `components/` : ni `#hex`, ni `rgb()`/`hsl()`/`oklch()`, ni palette Tailwind
 * (`bg-red-500`, `text-white`…), ni valeur arbitraire (`bg-[#…]`).
 */
const ROOT = join(__dirname, "..");
const SCANNED = ["app", "components"];
const THEME = join("app", "globals.css");

const PALETTE =
  "red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|slate|gray|zinc|neutral|stone|black|white";
const UTILITY =
  "bg|text|border|border-[trblxyse]|fill|stroke|ring|ring-offset|outline|from|via|to|shadow|divide|decoration|accent|caret|placeholder";

const RULES: { name: string; pattern: RegExp }[] = [
  {
    name: "couleur hexadécimale",
    pattern: /(?<![\w&/-])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b/g,
  },
  { name: "fonction de couleur", pattern: /\b(?:rgba?|hsla?|oklch|oklab|lab|lch|hwb)\(/g },
  {
    name: "palette Tailwind",
    pattern: new RegExp(`\\b(?:${UTILITY})-(?:${PALETTE})(?:-\\d{2,3})?(?:/\\d+)?\\b`, "g"),
  },
];

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.(tsx?|css)$/.test(name) && !/\.test\.tsx?$/.test(name) ? [path] : [];
  });
}

function violations(): string[] {
  const found: string[] = [];
  for (const file of SCANNED.flatMap((dir) => sources(join(ROOT, dir)))) {
    const path = relative(ROOT, file);
    if (path === THEME) continue;
    readFileSync(file, "utf8")
      .split("\n")
      .forEach((line, index) => {
        for (const { name, pattern } of RULES) {
          for (const match of line.matchAll(pattern)) {
            found.push(`${path}:${index + 1} ${name} « ${match[0]} »`);
          }
        }
      });
  }
  return found;
}

describe("aucune couleur en dur hors du thème", () => {
  it("app/ et components/ n'utilisent que les couleurs du thème", () => {
    expect(violations()).toEqual([]);
  });

  it("repère bien chaque forme interdite", () => {
    const samples = [
      'style={{ color: "#1E2320" }}',
      "fill: rgb(0 0 0)",
      'className="bg-emerald-600"',
      'className="text-white"',
      'className="border-black/40"',
    ];
    for (const sample of samples) {
      expect(
        RULES.some(({ pattern }) => sample.match(pattern)),
        sample,
      ).toBe(true);
    }
    expect(RULES.some(({ pattern }) => 'href="#main"'.match(pattern))).toBe(false);
    expect(RULES.some(({ pattern }) => 'className="bg-admin"'.match(pattern))).toBe(false);
  });
});
