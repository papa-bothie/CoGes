import { describe, expect, it } from "vitest";

import { displayNumber, qtyWithUnit } from "./units";

describe("qtyWithUnit", () => {
  it("accorde l'unité au pluriel à partir de 2", () => {
    expect(qtyWithUnit("2.000", "sac")).toBe("2 sacs");
    expect(qtyWithUnit("1.000", "bouteille")).toBe("1 bouteille");
    expect(qtyWithUnit("40.000", "kg")).toBe("40 kg");
    expect(qtyWithUnit("3", "inconnue")).toBe("3 inconnue");
  });
});

describe("displayNumber", () => {
  it("lit un numéro de pièce comme la maquette : V-001044 → 1044", () => {
    expect(displayNumber("V-001044")).toBe("1044");
    expect(displayNumber("R-000007")).toBe("7");
    expect(displayNumber("SANS-NUMERO")).toBe("SANS-NUMERO");
  });
});
