import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { contrast, grey, luminance } from "@/test/contrast";

/**
 * Facture A4 claire (lot A, ADR 0130, amende l'ADR 0112) : trois jetons seulement
 * (`--coges-facture-accent`, `-accent-clair`, `-filet`) ; l'accent clair est le seul fond
 * teinté (luminance 0,80 au moins), l'encre, le gris et l'accent y sont lisibles (4,5:1),
 * et le filet reste visible imprimé en gris. Les valeurs viennent du bloc clair de
 * globals.css : la facture est du papier, claire en sombre aussi.
 */
const css = readFileSync(join(__dirname, "..", "..", "globals.css"), "utf8");
const light = css.slice(css.indexOf(":root"), css.indexOf("\n}", css.indexOf(":root")));

function token(name: string): string {
  const match = new RegExp(`--${name}:\\s*(#[0-9a-f]{6})`, "i").exec(light);
  if (!match?.[1]) throw new Error(`jeton ${name} absent du bloc clair`);
  return match[1];
}

describe("contraste de la facture claire", () => {
  const surfaces = ["coges-recu-papier", "coges-facture-accent-clair", "coges-recu-entete"];
  const inks = ["coges-recu-encre", "coges-recu-gris", "coges-facture-accent"];

  it("chaque fond de la facture est clair : luminance 0,80 au moins", () => {
    for (const surface of surfaces) {
      expect(luminance(token(surface)), surface).toBeGreaterThanOrEqual(0.8);
    }
  });

  it("encre, gris et accent sur chaque fond : AA au moins, et encore en gris imprimé", () => {
    for (const surface of surfaces) {
      for (const ink of inks) {
        expect(contrast(token(ink), token(surface)), `${ink}/${surface}`).toBeGreaterThanOrEqual(
          4.5,
        );
        expect(contrast(grey(token(ink)), grey(token(surface)))).toBeGreaterThanOrEqual(4.5);
      }
    }
  });

  it("le filet se voit sur le papier et l'accent clair, même en gris (3:1)", () => {
    for (const surface of ["coges-recu-papier", "coges-facture-accent-clair"]) {
      expect(
        contrast(grey(token("coges-facture-filet")), grey(token(surface))),
      ).toBeGreaterThanOrEqual(3);
    }
  });

  it("le papier reprend les jetons clairs : `.papier` partage le bloc de `:root`", () => {
    expect(css).toMatch(/:root,\s*\.papier\s*\{/);
  });
});
