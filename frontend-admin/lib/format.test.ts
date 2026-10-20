import { describe, expect, it } from "vitest";

import { formatDate, formatDateTime } from "./format";

describe("formats d'affichage", () => {
  it("date en jj/mm/aaaa, heure sur 24 h", () => {
    expect(formatDate("2026-10-06T10:45:00Z")).toBe("06/10/2026");
    expect(formatDateTime("2026-10-06T22:05:00Z")).toBe("06/10/2026 à 22:05");
  });

  it("absence de valeur", () => {
    expect(formatDate(null)).toBe("—");
    expect(formatDateTime(null)).toBe("Jamais");
  });
});
