import { describe, expect, it } from "vitest";

import { PERIOD_LABELS, addMonths, nextPeriodEnd } from "./periods";

const NOW = new Date("2026-11-27T10:00:00Z");

describe("durées payées (ADR 0132, 0134)", () => {
  it("nomme les trois durées", () => {
    expect([PERIOD_LABELS[1], PERIOD_LABELS[6], PERIOD_LABELS[12]]).toEqual([
      "1 mois",
      "6 mois",
      "1 an",
    ]);
  });

  it("ramène au dernier jour du mois, comme le serveur", () => {
    const iso = (value: string, months: number) =>
      addMonths(new Date(value), months).toISOString().slice(0, 10);
    expect(iso("2027-08-31T12:00:00Z", 6)).toBe("2028-02-29");
    expect(iso("2028-08-31T12:00:00Z", 6)).toBe("2029-02-28");
    expect(iso("2027-12-31T12:00:00Z", 6)).toBe("2028-06-30");
    expect(iso("2026-01-31T12:00:00Z", 1)).toBe("2026-02-28");
    expect(iso("2028-02-29T12:00:00Z", 12)).toBe("2029-02-28");
  });

  it("part de l'ancienne fin pendant la grâce, sinon d'aujourd'hui (ADR 0133)", () => {
    const end = (status: string, current_period_end: string | null, months = 6) =>
      nextPeriodEnd({ status, current_period_end }, months, NOW).toISOString().slice(0, 10);
    // Fin d'essai : depuis le jour du paiement.
    expect(end("trial", null)).toBe("2027-05-27");
    // En cours ou dans les 3 jours de grâce : depuis l'ancienne fin.
    expect(end("active", "2026-12-15T10:00:00Z")).toBe("2027-06-15");
    expect(end("past_due", "2026-11-25T10:00:00Z")).toBe("2027-05-25");
    // En pause, ou fin oubliée depuis longtemps : depuis aujourd'hui.
    expect(end("suspended", "2026-11-25T10:00:00Z")).toBe("2027-05-27");
    expect(end("past_due", "2026-10-01T10:00:00Z", 1)).toBe("2026-12-27");
  });
});
