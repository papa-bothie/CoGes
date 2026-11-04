import { describe, expect, it } from "vitest";

import { nameWithHint, productHints } from "./product-hint";

describe("ce qui distingue un article (ADR 0108)", () => {
  it("donne la description, sinon la référence d'un homonyme, sinon rien", () => {
    const hints = productHints([
      { id: "a", name: "Huile", description: "1 litre", sku: "ART-0001" },
      { id: "b", name: "huile ", description: null, sku: "ART-0002" },
      { id: "c", name: "Riz", description: "  ", sku: "ART-0003" },
    ]);
    expect(hints.get("a")).toBe("1 litre");
    expect(hints.get("b")).toBe("Réf. ART-0002");
    expect(hints.has("c")).toBe(false);
  });

  it("ne prend pas deux lignes du même article pour des homonymes", () => {
    const hints = productHints([
      { id: "line-1", name: "Huile", sku: "ART-0001" },
      { id: "line-2", name: "Huile", sku: "ART-0001" },
    ]);
    expect(hints.size).toBe(0);
  });

  it("nomme l'article avec ce qui le distingue", () => {
    expect(nameWithHint("Huile", "5 litres")).toBe("Huile, 5 litres");
    expect(nameWithHint("Riz", undefined)).toBe("Riz");
  });
});
