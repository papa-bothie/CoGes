import { describe, expect, it } from "vitest";

import { labels } from "@/lib/labels";

import { attachmentName, periodName, preparedTitle, salesPeriod } from "./files";

describe("périodes d'un export de ventes (écran 24e)", () => {
  it("borne ce mois, le mois dernier et cette année", () => {
    expect(salesPeriod("month", "2026-10-06")).toEqual({ from: "2026-10-01", to: "2026-10-06" });
    expect(salesPeriod("last", "2026-10-06")).toEqual({ from: "2026-09-01", to: "2026-09-30" });
    expect(salesPeriod("last", "2026-01-15")).toEqual({ from: "2025-12-01", to: "2025-12-31" });
    expect(salesPeriod("year", "2026-10-06")).toEqual({ from: "2026-01-01", to: "2026-10-06" });
  });

  it("nomme la période d'un fichier préparé", () => {
    expect(periodName("2026-09-01", "2026-09-30")).toBe("septembre 2026");
    expect(periodName("2026-10-01", "2026-10-06")).toBe("octobre 2026");
    expect(periodName("2026-01-01", "2026-10-06")).toBe("2026");
    expect(periodName("2026-09-03", "2026-09-15")).toBe("03/09 au 15/09");
  });

  it("lit le nom du fichier envoyé par l'API", () => {
    expect(attachmentName('attachment; filename="ventes.xlsx"', "x")).toBe("ventes.xlsx");
    expect(attachmentName(null, "modele.csv")).toBe("modele.csv");
  });
});

describe("preparedTitle (ADR 0114)", () => {
  it("nomme chaque document de la file, daté ou à ce jour", () => {
    const f = labels.settingsScreens.files;
    expect(preparedTitle("sales", { date_from: "2026-09-01", date_to: "2026-09-30" }, null)).toBe(
      f.salesOf("septembre 2026"),
    );
    expect(preparedTitle("cash", { date_from: "2026-09-01", date_to: "2026-09-30" }, null)).toBe(
      f.cashOf("septembre 2026"),
    );
    expect(
      preparedTitle("expenses", { date_from: "2026-09-01", date_to: "2026-09-30" }, null),
    ).toBe(f.expensesOf("septembre 2026"));
    expect(preparedTitle("stock", {}, "Stock-2026-11-05-Boutique.pdf")).toBe(f.stock);
    expect(preparedTitle("debts", {}, null)).toBe(f.debts);
    expect(preparedTitle("sales", {}, "ventes.xlsx")).toBe("ventes.xlsx");
  });
});
