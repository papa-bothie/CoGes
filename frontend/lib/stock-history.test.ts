import { describe, expect, it } from "vitest";

import { historyKind, historyPhrase, historyQty, historyWhen } from "./stock-history";

const item = (patch: Record<string, unknown>) => ({
  movement_id: "m",
  occurred_at: "2026-10-06T10:42:00Z",
  type: "sale_out" as const,
  reason_code: null,
  qty_delta: "-1.000",
  counterparty: null,
  is_reversal: false,
  ...patch,
});

describe("historique d'un article en phrases", () => {
  it("dit qui a acheté, qui a livré et pourquoi", () => {
    expect(historyPhrase(item({ counterparty: "Awa Diop" }))).toBe("Vendu à Awa Diop");
    expect(historyPhrase(item({}))).toBe("Vendu");
    expect(
      historyPhrase(
        item({ type: "purchase_in", counterparty: "Grossiste Sandaga", qty_delta: "10" }),
      ),
    ).toBe("Livraison de Grossiste Sandaga");
    expect(historyPhrase(item({ type: "loss", reason_code: "damaged" }))).toBe("Abîmé");
    expect(historyPhrase(item({ type: "adjustment", reason_code: "count_error" }))).toBe(
      "Correction : erreur de comptage",
    );
    expect(historyPhrase(item({ type: "customer_return_in", counterparty: "Ibrahima Ba" }))).toBe(
      "Rendu par Ibrahima Ba",
    );
  });

  it("donne la quantité signée avec son unité et la teinte", () => {
    expect(historyQty(item({}), "sac")).toBe("−1 sac");
    expect(historyQty(item({ qty_delta: "10.000" }), "sac")).toBe("+10 sacs");
    expect(historyKind(item({}))).toBe("out");
    expect(historyKind(item({ type: "loss" }))).toBe("loss");
    expect(historyKind(item({ type: "adjustment", qty_delta: "2" }))).toBe("fix");
    expect(historyKind(item({ type: "purchase_in", qty_delta: "10" }))).toBe("in");
  });

  it("date comme la maquette", () => {
    const now = new Date("2026-10-06T10:45:00Z");
    expect(historyWhen("2026-10-06T10:42:00Z", "Africa/Dakar", now)).toBe("Aujourd'hui, 10 h 42");
    expect(historyWhen("2026-10-05T18:20:00Z", "Africa/Dakar", now)).toBe("Hier, 18 h 20");
    expect(historyWhen("2026-10-03T09:00:00Z", "Africa/Dakar", now)).toBe("Samedi 3 octobre");
  });
});
