import { describe, expect, it } from "vitest";

import { centsToAmount, refundCents } from "./refund";

describe("refundCents", () => {
  it("rend le prix des unités rendues, sans taxe ni remise", () => {
    const line = { qty: "5.000", unit_price: "1400.00", discount: "0.00", tax_rate: "0.0000" };
    expect(centsToAmount(refundCents(line, "2"))).toBe("2800.00");
    expect(refundCents(line, "0")).toBe(0n);
  });

  it("proratise la remise et arrondit net et taxe séparément", () => {
    // 3 × 1 000, remise 100, TVA 18 % : net 2 900, taxe 522, total 3 422.
    const line = { qty: "3.000", unit_price: "1000.00", discount: "100.00", tax_rate: "0.1800" };
    expect(centsToAmount(refundCents(line, "3"))).toBe("3422.00");
    // 1 sur 3 : net 1 000 − 33,333… = 966,67 ; taxe 174,00 → 1 140,67.
    expect(centsToAmount(refundCents(line, "1"))).toBe("1140.67");
  });
});
