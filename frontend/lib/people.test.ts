import { describe, expect, it } from "vitest";

import { labels } from "./labels";
import { agoText, initials, shortNames, sinceText, visitDay } from "./people";

const NOW = new Date("2026-10-06T10:45:00Z");
const ZONE = "Africa/Dakar";

describe("personnes", () => {
  it("dit les articles en quelques mots", () => {
    expect(shortNames(["Riz brisé 25 kg", "Huile Dinor 1 L", "Bougies paquet"])).toBe(
      "Riz, huile, bougies",
    );
    expect(shortNames(["Riz brisé", "Riz parfumé", "Sucre"])).toBe("Riz, sucre");
    expect(shortNames([])).toBe("");
  });

  it("compte l'âge d'une dette en jours", () => {
    expect(sinceText("2026-09-24T09:00:00Z", ZONE, NOW)).toBe("Depuis 12 jours");
    expect(sinceText("2026-10-05T18:00:00Z", ZONE, NOW)).toBe("Depuis hier");
    expect(sinceText("2026-10-06T08:00:00Z", ZONE, NOW)).toBe("Depuis aujourd'hui");
  });

  it("dit quand en mots", () => {
    expect(agoText("2026-10-06T09:00:00Z", ZONE, NOW)).toBe("aujourd'hui");
    expect(agoText("2026-10-05T09:00:00Z", ZONE, NOW)).toBe("hier");
    expect(agoText("2026-10-03T09:00:00Z", ZONE, NOW)).toBe("samedi");
    expect(agoText("2026-09-22T09:00:00Z", ZONE, NOW)).toBe("il y a 2 semaines");
    expect(agoText("2026-06-01T09:00:00Z", ZONE, NOW)).toBe("il y a 4 mois");
  });

  it("nomme le jour d'une visite", () => {
    expect(visitDay("2026-10-06T09:58:00Z", ZONE, NOW)).toBe("Aujourd'hui");
    expect(visitDay("2026-10-05T09:58:00Z", ZONE, NOW)).toBe("Hier");
    expect(visitDay("2026-10-03T09:58:00Z", ZONE, NOW)).toBe("Samedi 3 octobre");
  });

  it("tire les initiales", () => {
    expect(initials("Moussa Fall")).toBe("MF");
    expect(initials("Grossiste Sandaga du marché")).toBe("GS");
    expect(initials("Awa")).toBe("A");
  });
});

describe("rappel de dette", () => {
  const remind = labels.peopleScreens.customer.reminder;

  it("donne le numéro Wave de la boutique quand il est enregistré", () => {
    expect(remind("Moussa", "Fatou", "Alimentation Keur Fatou", "25 000 F", "77 123 45 67")).toBe(
      "Bonjour Moussa, c’est Fatou, de la boutique Alimentation Keur Fatou. Il reste 25 000 F à régler sur vos achats. Vous pouvez payer à la boutique ou par Wave au 77 123 45 67. Merci !",
    );
  });

  it("se contente de la boutique sans numéro Wave", () => {
    expect(remind("Awa", "Modou", "Boutique", "4 000 F", null)).toMatch(
      /Vous pouvez payer à la boutique\. Merci !$/,
    );
  });
});
