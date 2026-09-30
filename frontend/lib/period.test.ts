import { describe, expect, it } from "vitest";

import { addDays, resolvePeriod, todayIn } from "./period";

// 30/09/2026 à 23 h 30 UTC : déjà le 1er octobre à Paris, encore le 30 à Dakar.
const NOW = new Date("2026-09-30T23:30:00Z");

describe("période d'analyse", () => {
  it("prend le jour dans le fuseau de l'entreprise", () => {
    expect(todayIn("Africa/Dakar", NOW)).toBe("2026-09-30");
    expect(todayIn("Europe/Paris", NOW)).toBe("2026-10-01");
  });

  it("décale les jours calendaires, fins de mois comprises", () => {
    expect(addDays("2026-03-01", -1)).toBe("2026-02-28");
    expect(addDays("2026-12-31", 1)).toBe("2027-01-01");
  });

  it("résout les préréglages, bornes incluses", () => {
    const at = (period: string) =>
      resolvePeriod({ period, from: null, to: null }, "Africa/Dakar", NOW);
    expect(at("7d")).toEqual({ preset: "7d", from: "2026-09-24", to: "2026-09-30" });
    expect(at("30d")).toEqual({ preset: "30d", from: "2026-09-01", to: "2026-09-30" });
    expect(at("90d").from).toBe("2026-07-03");
    expect(at("month")).toEqual({ preset: "month", from: "2026-09-01", to: "2026-09-30" });
  });

  it("par défaut : les 30 derniers jours", () => {
    expect(resolvePeriod({ period: null, from: null, to: null }, "UTC", NOW).preset).toBe("30d");
    expect(resolvePeriod({ period: "n'importe", from: null, to: null }, "UTC", NOW).preset).toBe(
      "30d",
    );
  });

  it("refuse une période personnalisée inversée ou incomplète", () => {
    const tz = "Africa/Dakar";
    expect(
      resolvePeriod({ period: "custom", from: "2026-09-01", to: "2026-09-10" }, tz, NOW),
    ).toEqual({ preset: "custom", from: "2026-09-01", to: "2026-09-10" });
    expect(
      resolvePeriod({ period: "custom", from: "2026-09-10", to: "2026-09-01" }, tz, NOW).preset,
    ).toBe("30d");
    expect(resolvePeriod({ period: "custom", from: "2026-09-10", to: null }, tz, NOW).preset).toBe(
      "30d",
    );
  });
});
