import { describe, expect, it } from "vitest";

import { texte, TRIAL_DAYS } from "./vitrine-texte";
import { vitrine } from "./vitrine";

/** Tout le texte affiché, à plat. */
function allText(value: unknown): string {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.map(allText).join("\n");
  if (value && typeof value === "object") return Object.values(value).map(allText).join("\n");
  return "";
}

const ALL = allText(texte);

describe("vitrine : promesses (prompt 37, ADR 0115)", () => {
  it("ne promet jamais un fonctionnement sans connexion", () => {
    expect(ALL).not.toMatch(/sans (connexion|internet|réseau)|hors[- ]ligne|offline/i);
  });

  it("l'essai a la durée de l'ADR 0091", () => {
    expect(TRIAL_DAYS).toBe(30);
    expect(ALL).not.toMatch(/\b(?!30\b)\d+ jours d'essai/);
  });

  it("aucun prix tant que vitrine.pricing est vide", () => {
    expect(vitrine.pricing).toBeNull();
    expect(ALL).not.toMatch(/\d[\d  ]*\s?(F|FCFA|francs)\b/);
  });

  it("aucun bouton « Créer ma boutique » (lot Inscription)", () => {
    expect(ALL).not.toMatch(/créer ma boutique|inscri/i);
  });

  it("aucun lien vers des pages légales qui n'existent pas encore", () => {
    expect(ALL).not.toMatch(/\/conditions|\/confidentialite|cgu|cgv/i);
  });

  it("jamais « meilleur produit » ni chiffre inventé", () => {
    expect(ALL).not.toMatch(/meilleur produit|\d+ ?%/i);
  });

  it("six fonctionnalités et cinq à six questions", () => {
    expect(texte.features.items).toHaveLength(6);
    expect(texte.faq.items.length).toBeGreaterThanOrEqual(5);
    expect(texte.faq.items.length).toBeLessThanOrEqual(6);
  });

  it("les horaires du support figurent dans la FAQ et le pied de page", () => {
    expect(texte.footer.hours).toBe(vitrine.supportHours);
    expect(ALL.toLowerCase()).toContain(vitrine.supportHours.slice(1).toLowerCase());
  });
});

describe("vitrine : titre qui change de mot (prompt 38, A1)", () => {
  const minuscule = (mot: string) => mot.charAt(0).toLowerCase() + mot.slice(1);

  it("les trois mots relayés et la suite redonnent exactement hero.title", () => {
    const { mots, suite } = texte.hero.rotation;
    expect(mots).toEqual(["Les ventes", "Le stock", "L'argent"]);
    expect(`${mots[0]}, ${minuscule(mots[1])} et ${minuscule(mots[2])} ${suite}`).toBe(
      texte.hero.title,
    );
  });

  it("la phrase de fin (zone animée) est le début exact de hero.title", () => {
    const { complet, suite } = texte.hero.rotation;
    expect(`${complet} ${suite}`).toBe(texte.hero.title);
  });
});
