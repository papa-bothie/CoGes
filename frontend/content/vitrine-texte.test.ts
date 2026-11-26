import { describe, expect, it } from "vitest";

import { formatAmount } from "@/lib/format/money";

import { texte, TRIAL_DAYS } from "./vitrine-texte";
import offres from "./offres.json";
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

  it("les offres viennent de la source partagée, et aucun prix n'est écrit dans les textes", () => {
    // Prompt 41 (ADR 0132) : remplace « aucun prix tant que vitrine.pricing est vide ».
    // Les montants sont affichés par « Nos offres » depuis `content/offres.json` seulement
    // (`components/vitrine/offres.test.tsx`), jamais écrits à la main dans un texte.
    expect(vitrine.pricing).toBe(offres.plans);
    expect(vitrine.pricing.map((plan) => plan.code)).toEqual(["starter", "business", "premium"]);
    // Seule exception : la mini-caisse (A9), une vente d'exemple aux prix des articles de la
    // démo, jamais un prix de CoGes (vérifié plus bas : elle se dit « exemple »).
    const hero = Object.entries(texte.hero).filter(([cle]) => cle !== "caisse");
    expect(allText({ ...texte, hero })).not.toMatch(/\d[\d  ]*\s?(F|FCFA|francs)\b/);
  });

  it("navigation : « Tarifs » à la place de « Comment ça marche » (prompt 42)", () => {
    expect(texte.nav.pricing).toBe("Tarifs");
    expect(allText(texte.nav)).not.toMatch(/comment ça marche/i);
    // La section reste : son titre n'est pas un texte de la navigation.
    expect(texte.nav).not.toHaveProperty("howItWorks");
  });

  it("carte d'essai : durée et offre tirées de la source, aucun montant écrit à la main", () => {
    // Le « 0 F » est formaté par la section depuis `offres.trialPrice`, jamais écrit ici.
    expect(offres.trialPrice).toBe(0);
    expect(texte.offers.trialCard.period).toBe(`pendant ${offres.trialDays} jours`);
    const plan = offres.plans.find((item) => item.code === offres.trialPlan)!;
    expect(texte.offers.trialCard.includes).toBe(`Toutes les fonctions de CoGes ${plan.name}`);
    expect(allText(texte.offers.trialCard)).not.toMatch(/\d[\d  ]*\s?(F|FCFA|francs)\b/);
  });

  it("aucun bouton « Créer ma boutique » (lot Inscription)", () => {
    expect(ALL).not.toMatch(/créer ma boutique|inscri/i);
  });

  it("aucun lien vers des pages légales qui n'existent pas encore", () => {
    expect(ALL).not.toMatch(/\/conditions|\/confidentialite|cgu|cgv/i);
  });

  it("jamais « meilleur produit » ; « 10 % » seulement dans la bascule annuelle", () => {
    expect(ALL).not.toMatch(/meilleur produit/i);
    const { annual, ...rest } = texte.offers;
    expect(annual).toBe(`Par an (-${offres.annualDiscountPercent} %)`);
    expect(allText({ ...texte, offers: rest })).not.toMatch(/\d+ ?%/);
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

describe("vitrine : slogan (prompt 40, lot A, R3)", () => {
  const SLOGAN = "Une meilleure façon de gérer son commerce.";

  it("le texte exact est dans le pied de page", () => {
    expect(texte.footer.slogan).toBe(SLOGAN);
  });

  it("il n'apparaît qu'une seule fois", () => {
    expect(ALL.split(SLOGAN)).toHaveLength(2);
  });
});
