import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { BRAND_COLORS } from "./brand-colors";

/** Valeur claire d'un jeton : la première définition, celle de `:root`. */
function token(name: string): string {
  const css = readFileSync(join(__dirname, "..", "app", "globals.css"), "utf8");
  const match = new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`).exec(css);
  if (!match?.[1]) throw new Error(`jeton --${name} introuvable`);
  return match[1].toLowerCase();
}

describe("couleurs du manifeste (ADR 0102)", () => {
  it("sont celles des jetons de la maquette", () => {
    expect(BRAND_COLORS.theme).toBe(token("coges-vert-marque"));
    expect(BRAND_COLORS.background).toBe(token("coges-papier"));
  });
});
