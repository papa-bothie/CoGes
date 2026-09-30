import { describe, expect, it } from "vitest";

import { formatQty, formatQtyWithUnit } from "./qty";

describe("formatQty", () => {
  it("retire les zéros inutiles", () => {
    expect(formatQty("12.500")).toBe("12,5");
    expect(formatQty("3.000")).toBe("3");
    expect(formatQty("0.125")).toBe("0,125");
  });

  it("groupe les milliers et accepte une unité", () => {
    expect(formatQty("1500.000", "kg")).toBe("1 500 kg");
  });

  it("n'invente rien pour une valeur absente", () => {
    expect(formatQty(null)).toBe("—");
    expect(formatQty("abc")).toBe("—");
  });
});

describe("formatQtyWithUnit", () => {
  it("accorde l'unité à partir de 2", () => {
    expect(formatQtyWithUnit("1.000", "pièce", "pièces")).toBe("1 pièce");
    expect(formatQtyWithUnit("1.500", "litre", "litres")).toBe("1,5 litre");
    expect(formatQtyWithUnit("7.000", "pièce", "pièces")).toBe("7 pièces");
    expect(formatQtyWithUnit(null, "pièce", "pièces")).toBe("—");
  });
});
