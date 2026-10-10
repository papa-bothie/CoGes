import { describe, expect, it } from "vitest";

import { shelfClass, shelfColor } from "./shelf-colors";

describe("couleur d'un rayon", () => {
  it("garde la couleur choisie, sinon la tire du nom, toujours la même", () => {
    expect(shelfColor({ name: "Céréales", color: 1 })).toBe(1);
    expect(shelfClass({ name: "Céréales", color: 3 })).toBe("bg-article-11");
    const derived = shelfColor({ name: "Produits frais" });
    expect(derived).toBeGreaterThanOrEqual(1);
    expect(derived).toBeLessThanOrEqual(8);
    expect(shelfColor({ name: "Produits frais", color: null })).toBe(derived);
  });
});
