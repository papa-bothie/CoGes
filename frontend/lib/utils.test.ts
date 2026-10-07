import { describe, expect, it } from "vitest";

import { cn } from "./utils";

describe("cn", () => {
  it("garde une taille de la maquette à côté d'une couleur de texte", () => {
    expect(cn("text-libelle", "text-primary-foreground")).toBe(
      "text-libelle text-primary-foreground",
    );
    expect(cn("text-titre-page text-foreground")).toBe("text-titre-page text-foreground");
  });

  it("remplace un rayon ou une hauteur par ceux de la maquette", () => {
    expect(cn("rounded-md", "rounded-bouton")).toBe("rounded-bouton");
    expect(cn("min-h-11", "min-h-bouton")).toBe("min-h-bouton");
    expect(cn("text-sm", "text-libelle")).toBe("text-libelle");
  });
});
