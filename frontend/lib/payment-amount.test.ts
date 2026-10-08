import { describe, expect, it } from "vitest";

import {
  billShortcuts,
  changeDue,
  debtPaymentCheck,
  debtShortcuts,
  partPaymentCheck,
  partShortcuts,
  wholeUnits,
} from "./payment-amount";

const NBSP = "\u00a0";
/** Espaces insécables dans les montants (« 25 000 F »), comme `formatAmount`. */
const f = (text: string) => text.replace(/(\d) (?=\d|F\b)/g, `$1${NBSP}`);

describe("montants tapés librement", () => {
  it("lit la partie entière d'un montant de l'API", () => {
    expect(wholeUnits("25000.00")).toBe(25000n);
    expect(wholeUnits("")).toBe(0n);
    expect(wholeUnits(null)).toBe(0n);
  });

  it("propose « Tout », « La moitié » arrondie à 500 et 5 000 F", () => {
    expect(debtShortcuts(25000n, "XOF").map((s) => s.label)).toEqual([
      f("Tout : 25 000 F"),
      f("La moitié : 12 500 F"),
      f("5 000 F"),
    ]);
    // Rien au-delà de ce qui est dû.
    expect(debtShortcuts(4000n, "XOF").map((s) => s.value)).toEqual(["4000", "2000"]);
  });

  it("dit ce qui restera, ou que c'est trop", () => {
    expect(debtPaymentCheck("", 25000n, "client", "XOF")).toMatchObject({
      ok: false,
      message: "Tapez le montant reçu, ou touchez un bouton",
    });
    expect(debtPaymentCheck("21000", 25000n, "client", "XOF")).toMatchObject({
      ok: true,
      message: f("Il restera 4 000 F à payer"),
    });
    expect(debtPaymentCheck("25000", 25000n, "client", "XOF").message).toBe(
      "Il ne devra plus rien",
    );
    expect(debtPaymentCheck("30000", 25000n, "client", "XOF")).toMatchObject({
      ok: false,
      tone: "trop",
      message: f("C’est plus que ce qu’il doit (25 000 F)"),
    });
    expect(debtPaymentCheck("130000", 120000n, "fournisseur", "XOF").message).toBe(
      f("C’est plus que ce que vous devez (120 000 F)"),
    );
  });

  it("une partie de la vente reste sous le total", () => {
    expect(partPaymentCheck("9000", 21000n, "XOF").message).toBe(f("Il restera 12 000 F à payer"));
    expect(partPaymentCheck("21000", 21000n, "XOF")).toMatchObject({
      ok: false,
      message: "C’est le total ou plus : choisissez « Tout payé »",
    });
    expect(partShortcuts(21000n, "XOF").map((s) => s.value)).toEqual(["10500", "5500"]);
  });

  it("rend la monnaie au-dessus du total", () => {
    expect(billShortcuts(7500n, "XOF").map((s) => s.label)).toEqual([
      "Le compte juste",
      f("10 000 F"),
      f("20 000 F"),
      f("50 000 F"),
    ]);
    expect(changeDue(10000n, 7500n)).toBe(2500n);
    expect(changeDue(7500n, 7500n)).toBeNull();
  });
});
