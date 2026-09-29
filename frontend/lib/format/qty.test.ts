import { describe, expect, it } from "vitest";

import { formatQty } from "./qty";

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
