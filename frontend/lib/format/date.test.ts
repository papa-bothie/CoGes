import { describe, expect, it } from "vitest";

import {
  formatClock,
  formatDate,
  formatDateTime,
  formatDayLong,
  formatDayMonth,
  formatWeekdayShort,
} from "./date";

describe("formatDate", () => {
  it("affiche jj/mm/aaaa dans le fuseau de l'entreprise", () => {
    expect(formatDate("2026-09-29T10:00:00Z", "Africa/Dakar")).toBe("29/09/2026");
  });

  it("bascule de jour selon le fuseau, pas selon le navigateur", () => {
    // 23 h 30 UTC : encore le 29 à Dakar (UTC+0), déjà le 30 à Douala (UTC+1).
    expect(formatDate("2026-09-29T23:30:00Z", "Africa/Dakar")).toBe("29/09/2026");
    expect(formatDate("2026-09-29T23:30:00Z", "Africa/Douala")).toBe("30/09/2026");
  });

  it("ne décale jamais une date seule", () => {
    expect(formatDate("2026-01-01", "Pacific/Honolulu")).toBe("01/01/2026");
  });

  it("n'invente rien pour une valeur absente ou illisible", () => {
    expect(formatDate(null)).toBe("—");
    expect(formatDate("pas une date")).toBe("—");
  });
});

describe("formatDateTime", () => {
  it("affiche l'heure sur 24 h", () => {
    expect(formatDateTime("2026-09-29T14:05:00Z", "Africa/Dakar")).toBe("29/09/2026 14:05");
    expect(formatDateTime("2026-09-29T23:30:00Z", "Africa/Douala")).toBe("30/09/2026 00:30");
  });
});

describe("dates de la maquette v2", () => {
  it("écrit l'heure « 10 h 42 » dans le fuseau de l'entreprise", () => {
    expect(formatClock("2026-10-06T10:42:00Z", "Africa/Dakar")).toBe("10 h 42");
    expect(formatClock("2026-10-06T09:05:00Z", "Africa/Dakar")).toBe("9 h 05");
    expect(formatClock("2026-10-06T23:30:00Z", "Europe/Paris")).toBe("1 h 30");
  });

  it("écrit le jour en toutes lettres et l'abrège sous une barre", () => {
    expect(formatDayLong("2026-10-06")).toBe("Mardi 6 octobre");
    expect(formatWeekdayShort("2026-09-30")).toBe("Mer");
    expect(formatWeekdayShort("2026-10-04")).toBe("Dim");
    expect(formatDayMonth("2026-10-20")).toBe("20 octobre");
    expect(formatDayMonth("2026-10-20T23:30:00Z", "Africa/Dakar")).toBe("20 octobre");
  });
});
