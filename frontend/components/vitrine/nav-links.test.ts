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
const offres = readFileSync(join(ROOT, "components", "vitrine", "offres.tsx"), "utf8");

describe("vitrine : navigation", () => {
  it("Fonctionnalités, Tarifs, Questions, dans cet ordre (prompt 42)", () => {
    expect(NAV_LINKS.map((link) => link.anchor)).toEqual([
      "fonctionnalites",
      "offres",
      "questions",
    ]);
    expect(NAV_LINKS.map((link) => link.label)).toEqual(["Fonctionnalités", "Tarifs", "Questions"]);
  });

  for (const { anchor } of NAV_LINKS) {
    it(`#${anchor} existe dans la page, une seule fois`, () => {
      const source = anchor === "offres" ? offres : page;
      expect(source.match(new RegExp(`id="${anchor}"`, "g"))).toHaveLength(1);
      expect(source).toMatch(new RegExp(`id="${anchor}"\\s+tabIndex=\\{-1\\}`));
    });
  }

  it("« Comment ça marche » quitte la navigation, la section reste sur la page", () => {
    expect(NAV_LINKS.map((link) => link.label)).not.toContain("Comment ça marche");
    expect(texte.nav).not.toHaveProperty("howItWorks");
    expect(page.match(/id="comment"/g)).toHaveLength(1);
    expect(page).toContain("<NosOffres");
  });

  it("l'en-tête et le menu mobile prennent tous deux la même liste", () => {
    expect(header).toContain("NAV_LINKS");
    expect(menu).toContain("NAV_LINKS");
    expect(header).not.toMatch(/href="#(fonctionnalites|comment|offres|questions)"/);
    expect(menu).not.toMatch(/href="#(fonctionnalites|comment|offres|questions)"/);
  });

  it("le hero n'a plus de lien « Voir comment ça marche » (aucun texte orphelin)", () => {
    expect(texte.hero).not.toHaveProperty("howItWorks");
    expect(page).not.toContain('href="#comment"');
  });
});
