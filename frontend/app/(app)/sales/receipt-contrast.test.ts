import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * Facture A4 au vert CoGes : le texte blanc (`--coges-sur-action`) sur le bandeau
 * (`--coges-vert-marque`) et sur les pastilles (`--coges-vert-action`) reste lisible, AA
 * (4,5:1) au moins, et le bandeau imprimé en gris garde un texte blanc lisible. Les valeurs
 * viennent du bloc clair de globals.css : la facture est du papier, claire en sombre aussi.
 */
const css = readFileSync(join(__dirname, "..", "..", "globals.css"), "utf8");
const light = css.slice(css.indexOf(":root"), css.indexOf("\n}", css.indexOf(":root")));

function token(name: string): string {
  const match = new RegExp(`--${name}:\\s*(#[0-9a-f]{6})`, "i").exec(light);
  if (!match?.[1]) throw new Error(`jeton ${name} absent du bloc clair`);
  return match[1];
}

function channel(value: number): number {
  const c = value / 255;
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((start) => parseInt(hex.slice(start, start + 2), 16));
  return 0.2126 * channel(r!) + 0.7152 * channel(g!) + 0.0722 * channel(b!);
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi! + 0.05) / (lo! + 0.05);
}

/** Le gris qu'une imprimante noir et blanc tire d'une couleur (même luminance). */
function grey(hex: string): string {
  const level = Math.round(luminance(hex) ** (1 / 2.2) * 255)
    .toString(16)
    .padStart(2, "0");
  return `#${level}${level}${level}`;
}

describe("contraste de la facture verte", () => {
  it("blanc sur vert-marque et sur vert-action : AA au moins", () => {
    const white = token("coges-sur-action");
    expect(white).toBe("#ffffff");
    expect(contrast(white, token("coges-vert-marque"))).toBeGreaterThanOrEqual(7);
    expect(contrast(white, token("coges-vert-action"))).toBeGreaterThanOrEqual(4.5);
  });

  it("imprimé en noir et blanc, le bandeau reste lisible", () => {
    const white = token("coges-sur-action");
    expect(contrast(white, grey(token("coges-vert-marque")))).toBeGreaterThanOrEqual(4.5);
  });

  it("le papier reprend les jetons clairs : `.papier` partage le bloc de `:root`", () => {
    expect(css).toMatch(/:root,\s*\.papier\s*\{/);
  });
});
