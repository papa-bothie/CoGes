import { describe, expect, it } from "vitest";

import { formatAge, formatDate, formatDateTime, formatFcfa, formatTime } from "./format";

describe("formats d'affichage", () => {
  it("date en jj/mm/aaaa, heure sur 24 h", () => {
    expect(formatDate("2026-10-06T10:45:00Z")).toBe("06/10/2026");
    expect(formatDateTime("2026-10-06T22:05:00Z")).toBe("06/10/2026 à 22:05");
  });

  it("absence de valeur", () => {
    expect(formatDate(null)).toBe("—");
    expect(formatDateTime(null)).toBe("Jamais");
  });

  it("heure à la seconde et âges courts", () => {
    expect(formatTime("2026-10-06T10:45:07Z")).toBe("10:45:07");
    expect(formatAge(12.4)).toBe("12 s");
    expect(formatAge(250)).toBe("4 min");
    expect(formatAge(3 * 3600 + 5)).toBe("3 h");
    expect(formatAge(2 * 86400)).toBe("2 j");
    expect(formatAge(null)).toBe("—");
  });

  it("francs CFA sans décimales, espaces fines insécables", () => {
    expect(formatFcfa("14900.00")).toBe("14\u202f900\u202fFCFA");
    expect(formatFcfa("4900")).toBe("4\u202f900\u202fFCFA");
    expect(formatFcfa(null)).toBe("Sur devis");
  });
});
