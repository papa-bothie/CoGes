import { describe, expect, it } from "vitest";

import { receiptText, whatsappLink } from "./whatsapp";

const SALE = {
  sale_no: "V-001044",
  sold_at: "2026-10-06T09:58:00Z",
  total: "25000.00",
  paid_total: "15000.00",
  balance: "10000.00",
  items: [
    {
      product_name: "Riz brisé 25 kg",
      qty: "1.000",
      unit_price: "15500.00",
      line_total: "15500.00",
    },
    { product_name: "Huile Dinor 1 L", qty: "5.000", unit_price: "1400.00", line_total: "7000.00" },
  ],
};

describe("reçu par WhatsApp", () => {
  it("écrit le reçu en phrases courtes", () => {
    const text = receiptText(SALE, { shop: "Alimentation Keur Fatou", timeZone: "Africa/Dakar" });
    expect(text.split("\n")).toEqual([
      "Alimentation Keur Fatou",
      "Vente n° 1044 · 06/10/2026 09:58",
      "Riz brisé 25 kg : 1 × 15 500 F = 15 500 F",
      "Huile Dinor 1 L : 5 × 1 400 F = 7 000 F",
      "Total : 25 000 F",
      "Payé : 15 000 F",
      "Reste à payer : 10 000 F",
    ]);
  });

  it("vise le numéro du client s'il est complet, sinon laisse choisir", () => {
    expect(whatsappLink("Bonjour", "76 220 15 90")).toBe("https://wa.me/221762201590?text=Bonjour");
    expect(whatsappLink("A & B", null)).toBe("https://wa.me/?text=A%20%26%20B");
  });
});
