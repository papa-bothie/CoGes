import { describe, expect, it } from "vitest";

import { formatAmount } from "@/lib/format/money";

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
    // Seule exception : la mini-caisse (A9), une vente d'exemple aux prix des articles de la
    // démo, jamais un prix de CoGes (vérifié plus bas : elle se dit « exemple »).
    const hero = Object.entries(texte.hero).filter(([cle]) => cle !== "caisse");
    expect(allText({ ...texte, hero })).not.toMatch(/\d[\d  ]*\s?(F|FCFA|francs)\b/);
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

describe("vitrine : mini-caisse du hero (prompt 38, A9)", () => {
  const { lignes, resume } = texte.hero.caisse;
  const total = lignes.reduce((sum, ligne) => sum + ligne.quantite * ligne.prix, 0);

  it("trois articles de la démo Keur Fatou, à leurs prix de la démo", () => {
    expect(lignes.map((ligne) => [ligne.article, ligne.prix])).toEqual([
      ["Riz brisé 25 kg", 15500],
      ["Huile Dinor 1 L", 1400],
      ["Sucre en morceaux 1 kg", 900],
    ]);
    for (const ligne of lignes) expect(Number.isInteger(ligne.quantite * ligne.prix)).toBe(true);
  });

  it("se dit exemple de vente, sans prix de CoGes", () => {
    expect(resume).toMatch(/^Exemple de vente dans CoGes/);
    expect(allText(texte.hero.caisse)).not.toMatch(/abonnement|par mois|offre|essai/i);
  });

  it("le texte pour lecteur d'écran donne le total exact", () => {
    expect(total).toBe(21000);
    expect(resume).toContain(formatAmount(String(total)));
  });
});
