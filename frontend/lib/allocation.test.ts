import { describe, expect, it } from "vitest";

import { splitAcrossDebts } from "./allocation";

const DEBTS = [
  { id: "a", balance: "10000.00" },
  { id: "b", balance: "5000.00" },
  { id: "c", balance: "2500.00" },
];

describe("préremplissage d'un règlement réparti", () => {
  it("solde les dettes dans l'ordre, puis s'arrête", () => {
    expect(splitAcrossDebts("12000", DEBTS)).toEqual({ a: "10000.00", b: "2000.00" });
  });

  it("couvre tout sans jamais dépasser un solde", () => {
    expect(splitAcrossDebts("30000", DEBTS)).toEqual({
      a: "10000.00",
      b: "5000.00",
      c: "2500.00",
    });
  });

  it("n'affecte rien d'un montant nul ou illisible", () => {
    expect(splitAcrossDebts("0", DEBTS)).toEqual({});
    expect(splitAcrossDebts("abc", DEBTS)).toEqual({});
  });
});
