import { describe, expect, it } from "vitest";

import type { Schemas } from "@/lib/api/schema";

import { barHeight } from "@/components/finance/money-bars";
import { expenseIcon } from "./expense-icons";
import {
  bucketLabel,
  cashLineText,
  daysUntil,
  netAmount,
  paidDay,
  shortNumber,
  signedAmount,
} from "./money";

const line = (overrides: Partial<Schemas["CashJournalLine"]>) =>
  ({
    payment_id: "p",
    kind: "sale",
    paid_at: "2026-10-06T10:42:00Z",
    method: "wave",
    signed_amount: "12500.00",
    cancelled: false,
    is_reversal: false,
    reversal_of: null,
    cancel_reason: null,
    document_no: "V-001046",
    sale_id: "s",
    party_name: "Awa Diop",
    expense_label: null,
    ...overrides,
  }) as Schemas["CashJournalLine"];

describe("L'argent en mots", () => {
  it("signe les montants avec le vrai moins", () => {
    expect(signedAmount("275000.00", "XOF")).toBe("+275 000 F");
    expect(signedAmount("-35000.00", "XOF")).toBe("−" + "35 000 F");
    expect(signedAmount("0.00", "XOF")).toBe("0 F");
    expect(netAmount("-16000.00", "XOF")).toBe("−" + "16 000 F");
    expect(netAmount("12500.00", "XOF")).toBe("12 500 F");
  });

  it("nomme les barres par moment, par jour et par semaine", () => {
    const bucket = (key: string, start: string) => ({
      key,
      start,
      end: start,
      cash_in: "0",
      cash_out: "0",
    });
    expect(bucketLabel(bucket("afternoon", "2026-10-06"), "moment")).toBe("Après-midi");
    expect(bucketLabel(bucket("2026-10-07", "2026-10-07"), "day")).toBe("Mer");
    expect(bucketLabel(bucket("week-2", "2026-10-08"), "week")).toBe("Semaine 2");
  });

  it("garde 4 px à toute valeur non nulle", () => {
    expect(barHeight(0, 610000, 200)).toBe(0);
    expect(barHeight(1, 610000, 200)).toBe(4);
    expect(barHeight(610000, 610000, 200)).toBe(200);
  });

  it("dit chaque ligne de caisse en phrase", () => {
    expect(shortNumber("V-001046")).toBe("1046");
    expect(cashLineText(line({}))).toBe("Vente n° 1046 · Awa Diop");
    expect(cashLineText(line({ party_name: null }))).toBe("Vente n° 1046 · Client de passage");
    expect(cashLineText(line({ kind: "debt_in", party_name: "Aminata Sow" }))).toBe(
      "Dette encaissée · Aminata Sow",
    );
    expect(cashLineText(line({ kind: "expense", party_name: "Électricité" }))).toBe(
      "Dépense · Électricité",
    );
    expect(cashLineText(line({ is_reversal: true, cancel_reason: "Saisi deux fois" }))).toBe(
      "Annulation : Vente n° 1046 · Awa Diop (saisi deux fois)",
    );
  });

  it("date la plus grosse dépense et compte les jours d'échéance", () => {
    expect(paidDay("2026-10-06", "2026-10-06")).toBe("aujourd'hui");
    expect(paidDay("2026-10-05", "2026-10-06")).toBe("hier");
    expect(paidDay("2026-10-01", "2026-10-06")).toBe("le 1er octobre");
    expect(daysUntil("2026-10-10", "2026-10-06")).toBe(4);
  });

  it("devine l'icône d'un type de dépense", () => {
    expect(expenseIcon("Électricité")).not.toBe(expenseIcon("Loyer"));
    expect(expenseIcon("Facture d'eau")).toBe(expenseIcon("Eau"));
    expect(expenseIcon("Téléphone et internet")).toBe(expenseIcon("Crédit téléphone"));
    expect(expenseIcon("Cadeaux")).toBe(expenseIcon("Autre"));
  });
});
