import { describe, expect, it } from "vitest";

import { labels } from "./labels";
import { formatMetricValue, METRIC_TEXTS, METRICS } from "./metrics";

/** Formulations interdites par l'Architecture (tableau CORRECT / INTERDIT, Diagramme 7). */
const FORBIDDEN = [/meilleur/i, /top produit/i, /score/i, /en direct/i];

function allTexts(value: unknown): string[] {
  if (typeof value === "string") return [value];
  if (typeof value === "function") return [String(value("Produit A", 1, 2))];
  if (value && typeof value === "object") return Object.values(value).flatMap(allTexts);
  return [];
}

/** Espaces insécables (fine ou non) ramenées à une espace simple pour comparer. */
const plain = (text: string) => text.replace(/[\u00a0\u202f]/g, " ");

describe("métriques produit", () => {
  it("compte huit métriques, chacune nommée et définie", () => {
    expect(METRICS).toHaveLength(8);
    for (const metric of METRICS) {
      expect(METRIC_TEXTS[metric].label).not.toBe("");
      expect(METRIC_TEXTS[metric].definition).not.toBe("");
    }
  });

  it("n'emploie aucune formulation interdite", () => {
    const texts = [
      ...allTexts(METRIC_TEXTS),
      ...allTexts(labels.analytics),
      ...allTexts(labels.insights),
      ...allTexts(labels.forecast),
    ];
    for (const text of texts) {
      for (const pattern of FORBIDDEN) expect(text).not.toMatch(pattern);
    }
  });

  it("formate chaque valeur dans l'unité renvoyée par l'API", () => {
    expect(plain(formatMetricValue("125000.00", "XOF", "XOF"))).toBe("125 000 FCFA");
    expect(plain(formatMetricValue("12.500", "unité", "XOF"))).toBe("12,5 u.");
    expect(plain(formatMetricValue("7", "vente", "XOF"))).toBe("7 ventes");
    expect(plain(formatMetricValue("2.40", "fois", "XOF"))).toBe("2,4 ×");
    expect(plain(formatMetricValue("18.25", "%", "XOF"))).toBe("+18,3 %");
    expect(plain(formatMetricValue("-4.00", "%", "XOF"))).toBe("−4 %");
    expect(plain(formatMetricValue("0.00", "%", "XOF"))).toBe("0 %");
    expect(plain(formatMetricValue(null, "%", "XOF"))).toBe("—");
    expect(plain(formatMetricValue("13.048", "unité", "XOF", { estimate: true }))).toBe("13 u.");
    expect(plain(formatMetricValue("35.091", "unité", "XOF", { estimate: true }))).toBe("35,1 u.");
  });
});
