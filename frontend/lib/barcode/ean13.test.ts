import { describe, expect, it } from "vitest";

import { ean13CheckDigit, ean13Modules, isValidEan13 } from "./ean13";

describe("EAN-13", () => {
  it("calcule la clé comme le serveur", () => {
    // `internal_ean13(1)` et `internal_ean13(7)` côté API (app/core/codes.py).
    expect(ean13CheckDigit("200000000001")).toBe(5);
    expect(ean13CheckDigit("200000000007")).toBe(7);
    expect(isValidEan13("4006381333931")).toBe(true);
    expect(isValidEan13("4006381333932")).toBe(false);
  });

  it("dessine 95 modules avec les gardes", () => {
    const modules = ean13Modules("4006381333931");
    expect(modules).toHaveLength(95);
    expect(modules?.startsWith("101")).toBe(true);
    expect(modules?.slice(45, 50)).toBe("01010");
    expect(modules?.endsWith("101")).toBe(true);
  });

  it("encode un code connu module par module", () => {
    // 5901234123457 : exemple de référence de la norme (premier chiffre 5 → LGGLLG).
    expect(ean13Modules("5901234123457")).toBe(
      "101" +
        // 9 L, 0 G, 1 G, 2 L, 3 L, 4 G
        "0001011" +
        "0100111" +
        "0110011" +
        "0010011" +
        "0111101" +
        "0011101" +
        "01010" +
        // 1 2 3 4 5 7, jeu R
        "1100110" +
        "1101100" +
        "1000010" +
        "1011100" +
        "1001110" +
        "1000100" +
        "101",
    );
  });

  it("refuse un code invalide", () => {
    expect(ean13Modules("123")).toBeNull();
  });
});
