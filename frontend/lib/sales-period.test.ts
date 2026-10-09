import { describe, expect, it } from "vitest";

import { salesPeriodDays } from "./sales-period";

describe("salesPeriodDays", () => {
  it("borne chaque puce, la semaine depuis le lundi", () => {
    // Mardi 6 octobre 2026.
    expect(salesPeriodDays("today", "2026-10-06")).toEqual({
      from: "2026-10-06",
      to: "2026-10-06",
    });
    expect(salesPeriodDays("yesterday", "2026-10-06")).toEqual({
      from: "2026-10-05",
      to: "2026-10-05",
    });
    expect(salesPeriodDays("week", "2026-10-06")).toEqual({ from: "2026-10-05", to: "2026-10-06" });
    expect(salesPeriodDays("week", "2026-10-04")).toEqual({ from: "2026-09-28", to: "2026-10-04" });
    expect(salesPeriodDays("month", "2026-10-06")).toEqual({
      from: "2026-10-01",
      to: "2026-10-06",
    });
  });
});
