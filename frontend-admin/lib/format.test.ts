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

describe("dates relatives et noms courts", () => {
  const now = Date.parse("2026-10-24T12:00:00Z");
  it("dit l'ancienneté en mots", async () => {
    const { formatRelative } = await import("./format");
    expect(formatRelative(null, now)).toBe("Jamais");
    expect(formatRelative("2026-10-24T11:59:30Z", now)).toBe("à l'instant");
    expect(formatRelative("2026-10-24T11:15:00Z", now)).toBe("il y a 45 min");
    expect(formatRelative("2026-10-24T09:00:00Z", now)).toBe("il y a 3 h");
    expect(formatRelative("2026-10-23T09:00:00Z", now)).toBe("hier");
    expect(formatRelative("2026-10-21T09:00:00Z", now)).toBe("il y a 3 jours");
    expect(formatRelative("2026-07-01T09:00:00Z", now)).toBe("il y a 3 mois");
  });
  it("abrège le nom de famille", async () => {
    const { shortName } = await import("./format");
    expect(shortName("Aïssatou Diop")).toBe("Aïssatou D.");
    expect(shortName("Mame Diarra Bousso Ndiaye")).toBe("Mame Diarra Bousso N.");
    expect(shortName("Moussa")).toBe("Moussa");
  });
});
