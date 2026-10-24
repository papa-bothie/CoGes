import { describe, expect, it } from "vitest";

import { barHeight, bucketLabel, bucketTitle, formatDay, formatSpan } from "./stats";

describe("statistiques", () => {
  it("un jour s'écrit jj/mm/aaaa sans glisser d'un fuseau", () => {
    expect(formatDay("2026-10-01")).toBe("01/10/2026");
    expect(formatSpan("2026-10-01", "2026-10-24")).toBe("du 01/10/2026 au 24/10/2026");
    expect(formatSpan("2026-10-24", "2026-10-24")).toBe("le 24/10/2026");
  });

  it("une période se nomme par son mois ou par le lundi de sa semaine", () => {
    const october = { start: "2026-10-01", end: "2026-10-31", count: 3 };
    const week = { start: "2026-10-19", end: "2026-10-25", count: 1 };
    expect(bucketLabel(october, "month")).toBe("oct. 2026");
    expect(bucketLabel(week, "week")).toBe("19/10");
    expect(bucketTitle(week, "week")).toBe("Semaine du 19/10/2026 au 25/10/2026");
  });

  it("une barre suit la plus haute, et une valeur non nulle reste visible", () => {
    expect(barHeight(0, 10)).toBe(0);
    expect(barHeight(10, 10)).toBe(100);
    expect(barHeight(1, 1000)).toBe(4);
    expect(barHeight(0, 0)).toBe(0);
  });
});
