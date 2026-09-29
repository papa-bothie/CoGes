import { describe, expect, it } from "vitest";

import { formatMoney } from "./money";

const NNBSP = " "; // séparateur de milliers fr-FR (espace fine insécable)
const NBSP = " ";

describe("formatMoney", () => {
  it("formate un montant XOF sans décimales, avec FCFA", () => {
    expect(formatMoney("1234567.00")).toBe(`1${NNBSP}234${NNBSP}567${NBSP}FCFA`);
  });

  it("arrondit au franc, demi vers le haut, sans passer par un float", () => {
    expect(formatMoney("1234567.50")).toBe(`1${NNBSP}234${NNBSP}568${NBSP}FCFA`);
    expect(formatMoney("1234567.49")).toBe(`1${NNBSP}234${NNBSP}567${NBSP}FCFA`);
    expect(formatMoney("999.5")).toBe(`1${NNBSP}000${NBSP}FCFA`);
    expect(formatMoney("-0.4")).toBe(`0${NBSP}FCFA`);
  });

  it("garde la précision au-delà de Number.MAX_SAFE_INTEGER", () => {
    expect(formatMoney("123456789012345678.00", "XOF", { withCurrency: false })).toBe(
      ["123", "456", "789", "012", "345", "678"].join(NNBSP),
    );
  });

  it("affiche les négatifs", () => {
    expect(formatMoney("-2500.00")).toBe(`-2${NNBSP}500${NBSP}FCFA`);
  });

  it("garde deux décimales pour une devise à centimes", () => {
    expect(formatMoney("1234.5", "EUR")).toBe(`1${NNBSP}234,50${NBSP}EUR`);
    expect(formatMoney("0.005", "EUR")).toBe(`0,01${NBSP}EUR`);
  });

  it("n'invente rien pour une valeur absente ou illisible", () => {
    expect(formatMoney(null)).toBe("—");
    expect(formatMoney(undefined)).toBe("—");
    expect(formatMoney("")).toBe("—");
    expect(formatMoney("12,5")).toBe("—");
    expect(formatMoney("1e3")).toBe("—");
  });
});
