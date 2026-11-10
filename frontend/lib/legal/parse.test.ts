// @vitest-environment node
import { readdirSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { LEGAL_TEXTS, legalDocument } from "./documents";
import { displayVersion, parseLegal } from "./parse";

describe("textes légaux : lecture (ADR 0117)", () => {
  it("la version vient de la première ligne, jamais d'ailleurs", () => {
    const doc = parseLegal("<!-- version: 2026-12-01 -->\n# Titre\n\nTexte.\n");
    expect(doc.version).toBe("2026-12-01");
    expect(doc.title).toBe("Titre");
    expect(doc.tokens.some((token) => token.type === "heading")).toBe(false);
  });

  it("refuse un texte sans ligne de version, ou avec une date fausse, ou sans titre", () => {
    expect(() => parseLegal("# Titre\n")).toThrow(/version/);
    expect(() => parseLegal("\n<!-- version: 2026-12-01 -->\n# T\n")).toThrow(/version/);
    expect(() => parseLegal("<!-- version: 2026-13-45 -->\n# T\n")).toThrow(/invalide/);
    expect(() => parseLegal("<!-- version: 2026-12-01 -->\nTexte.\n")).toThrow(/titre/);
  });

  it("affiche la date au format jj/mm/aaaa", () => {
    expect(displayVersion("2026-12-01")).toBe("01/12/2026");
  });

  it("les deux textes déposés se lisent et nomment exactement content/legal/", () => {
    const dir = path.join(process.cwd(), "content", "legal");
    expect(readdirSync(dir).sort()).toEqual(Object.values(LEGAL_TEXTS).sort());
    for (const slug of Object.keys(LEGAL_TEXTS) as (keyof typeof LEGAL_TEXTS)[]) {
      const doc = legalDocument(slug);
      expect(doc.version).toMatch(/^\d{4}-\d{2}-\d{2}$/);
      expect(doc.title.length).toBeGreaterThan(5);
      expect(doc.tokens.some((token) => token.type === "table")).toBe(true);
    }
  });
});
