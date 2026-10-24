import { describe, expect, it } from "vitest";

import { NAV, currentHref } from "./nav";

describe("menu", () => {
  it("deux groupes, Accès puis Plateforme", () => {
    expect(NAV.map((group) => group.title)).toEqual(["Accès", "Plateforme"]);
    expect(NAV[0]!.items.map((item) => item.label)).toEqual([
      "Tableau de bord",
      "Entreprises",
      "Utilisateurs",
      "Équipe",
      "Journal",
    ]);
  });
  it("la page courante est le lien le plus précis", () => {
    expect(currentHref("/")).toBe("/");
    expect(currentHref("/companies/123")).toBe("/companies");
    expect(currentHref("/system/jobs")).toBe("/system/jobs");
    expect(currentHref("/system")).toBe("/system");
  });
});
