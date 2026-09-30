import { describe, expect, it } from "vitest";

import { dayEndIso, dayStartIso, zonedDateTimeIso } from "./zoned";

describe("bornes de journée", () => {
  it("Dakar est en UTC", () => {
    expect(dayStartIso("2026-09-01", "Africa/Dakar")).toBe("2026-09-01T00:00:00.000Z");
    expect(dayEndIso("2026-09-30", "Africa/Dakar")).toBe("2026-09-30T23:59:59.999Z");
  });

  it("suit le décalage d'un autre fuseau, heure d'été comprise", () => {
    expect(dayStartIso("2026-07-01", "Europe/Paris")).toBe("2026-06-30T22:00:00.000Z");
    expect(dayStartIso("2026-12-01", "Europe/Paris")).toBe("2026-11-30T23:00:00.000Z");
  });

  it("refuse une date illisible", () => {
    expect(dayStartIso("01/09/2026", "UTC")).toBeNull();
  });
});

describe("zonedDateTimeIso", () => {
  it("lit l'heure saisie dans le fuseau de l'entreprise", () => {
    expect(zonedDateTimeIso("2026-09-30T10:15", "Africa/Dakar")).toBe("2026-09-30T10:15:00.000Z");
    expect(zonedDateTimeIso("2026-07-01T10:15", "Europe/Paris")).toBe("2026-07-01T08:15:00.000Z");
    expect(zonedDateTimeIso("30/09/2026", "UTC")).toBeNull();
  });
});
