import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { texte } from "@/content/vitrine-texte";

import { NAV_LINKS } from "./nav-links";

/**
 * Navigation de la vitrine (prompt 39, bloc N, ADR 0123) : chaque ancre de l'en-tête et du
 * menu mobile mène à une section qui existe dans la page.
 */
const ROOT = join(__dirname, "..", "..");
const page = readFileSync(join(ROOT, "app", "(vitrine)", "page.tsx"), "utf8");
const header = readFileSync(join(ROOT, "components", "vitrine", "vitrine-header.tsx"), "utf8");
const menu = readFileSync(join(ROOT, "components", "vitrine", "mobile-menu.tsx"), "utf8");

describe("vitrine : navigation", () => {
  it("Fonctionnalités, Comment ça marche, Questions, dans cet ordre", () => {
    expect(NAV_LINKS.map((link) => link.anchor)).toEqual([
      "fonctionnalites",
      "comment",
      "questions",
    ]);
    expect(NAV_LINKS.map((link) => link.label)).toEqual([
      "Fonctionnalités",
      "Comment ça marche",
      "Questions",
    ]);
  });

  for (const { anchor } of NAV_LINKS) {
    it(`#${anchor} existe dans la page, une seule fois`, () => {
      expect(page.match(new RegExp(`id="${anchor}"`, "g"))).toHaveLength(1);
    });
  }

  it("l'en-tête et le menu mobile prennent tous deux la même liste", () => {
    expect(header).toContain("NAV_LINKS");
    expect(menu).toContain("NAV_LINKS");
    expect(header).not.toMatch(/href="#(fonctionnalites|comment|questions)"/);
    expect(menu).not.toMatch(/href="#(fonctionnalites|comment|questions)"/);
  });

  it("le hero n'a plus de lien « Voir comment ça marche » (aucun texte orphelin)", () => {
    expect(texte.hero).not.toHaveProperty("howItWorks");
    expect(page).not.toContain('href="#comment"');
  });
});
