import { readFileSync } from "node:fs";
import { join } from "node:path";

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LegalConsent } from "./legal-consent";

/**
 * Liens légaux seulement au moment d'accepter (prompt 40, lot A, ADR 0130) : plus aucun
 * lien sur les pages d'entrée ni dans le menu du compte ; la case d'acceptation les garde,
 * ouverts dans un nouvel onglet pour ne jamais faire perdre la saisie.
 */
const ROOT = join(__dirname, "..", "..");
const ENTRY_PAGES = [
  "app/(auth)/login/page.tsx",
  "app/(auth)/password/page.tsx",
  "app/(auth)/verification/page.tsx",
  "app/(auth)/verification/[jeton]/page.tsx",
  "app/(auth)/inscription/page.tsx",
];

describe("pages d'entrée sans liens légaux", () => {
  it.each(ENTRY_PAGES)("%s", (path) => {
    const source = readFileSync(join(ROOT, path), "utf8");
    expect(source).not.toMatch(/LegalLinks|\/conditions|\/confidentialite/);
  });

  it("menu du compte : aucune entrée vers les textes", () => {
    const source = readFileSync(join(ROOT, "components/shell/settings-menu.tsx"), "utf8");
    expect(source).not.toMatch(/\/conditions|\/confidentialite|labels\.legal/);
  });

  it("pied de la vitrine : « Confidentialité » seul, jamais « Conditions »", () => {
    const source = readFileSync(join(ROOT, "app/(vitrine)/page.tsx"), "utf8");
    expect(source).not.toMatch(/LegalLinks|\/conditions/);
    expect(source.match(/href="\/confidentialite"/g)).toHaveLength(1);
  });
});

describe("case d'acceptation", () => {
  it("porte les deux liens, ouverts dans un nouvel onglet sans lien vers la page d'origine", () => {
    render(<LegalConsent checked={false} onChange={() => undefined} />);
    const links = screen.getAllByRole("link");
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "/conditions",
      "/confidentialite",
    ]);
    for (const link of links) {
      expect(link).toHaveAttribute("target", "_blank");
      expect(link.getAttribute("rel")?.split(" ").sort()).toEqual(["noopener", "noreferrer"]);
      expect(link).toHaveAccessibleName(/nouvel onglet/);
    }
  });
});
