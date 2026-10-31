import { describe, expect, it } from "vitest";

import { addScannedLine, cleanScannedCode, stockEffects, type DeliveryLine } from "./delivery-scan";

const rice = { product_id: "riz", name: "Riz 25 kg", unit: "sac" as const, qty_on_hand: "5.000" };
const oil = {
  product_id: "huile",
  name: "Huile 1 L",
  unit: "bouteille" as const,
  qty_on_hand: "0",
};

describe("code lu par la caméra ou la douchette", () => {
  it("retire les espaces, partout", () => {
    expect(cleanScannedCode("  4006 3813\t33931\n")).toBe("4006381333931");
    expect(cleanScannedCode("   ")).toBe("");
  });
});

describe("ligne ajoutée par un scan", () => {
  it("ajoute l'article avec une pièce et le dernier prix d'achat", () => {
    const { lines, merged } = addScannedLine([], rice, "100");
    expect(merged).toBe(false);
    expect(lines).toEqual([{ product: rice, qty: "1", cost: "100" }]);
  });

  it("le même code scanné une seconde fois ajoute 1 à la ligne, sans doublon", () => {
    const first = addScannedLine([], rice, "100").lines;
    const typed: DeliveryLine[] = [{ ...first[0]!, qty: "19", cost: "120" }];
    const { lines, merged } = addScannedLine(typed, rice, "100");
    expect(merged).toBe(true);
    expect(lines).toEqual([{ product: rice, qty: "20", cost: "120" }]);
  });

  it("une quantité vide repart d'une pièce, une décimale est gardée", () => {
    expect(addScannedLine([{ product: rice, qty: "", cost: "" }], rice, "1").lines[0]!.qty).toBe(
      "1",
    );
    expect(addScannedLine([{ product: rice, qty: "2,5", cost: "" }], rice, "1").lines[0]!.qty).toBe(
      "3.5",
    );
  });

  it("un autre article s'ajoute à la suite", () => {
    const { lines } = addScannedLine([{ product: rice, qty: "3", cost: "100" }], oil, "");
    expect(lines.map((line) => line.product.product_id)).toEqual(["riz", "huile"]);
  });
});

describe("récapitulatif avant validation", () => {
  it("dit l'effet exact sur le stock de chaque ligne", () => {
    expect(
      stockEffects([
        { product: rice, qty: "20", cost: "120" },
        { product: oil, qty: "12", cost: "900" },
      ]),
    ).toEqual(["Riz 25 kg : 5 → 25", "Huile 1 L : 0 → 12"]);
  });

  it("ignore une ligne sans quantité lisible", () => {
    expect(stockEffects([{ product: rice, qty: "", cost: "120" }])).toEqual([]);
  });
});
