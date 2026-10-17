import { describe, expect, it } from "vitest";

import {
  contactOf,
  historyWhen,
  seenWhen,
  shortClock,
  temporaryDeadline,
  toggleAbility,
} from "./settings";

const DAKAR = "Africa/Dakar";
const NOW = new Date("2026-10-06T10:45:00Z");

describe("moments des réglages (ADR 0075)", () => {
  it("écrit l'heure ronde sans minutes, comme la maquette", () => {
    expect(shortClock("2026-10-05T19:00:00Z", DAKAR)).toBe("19 h");
    expect(shortClock("2026-10-05T09:05:00Z", DAKAR)).toBe("9 h 05");
  });

  it("dit quand une personne a été vue", () => {
    expect(seenWhen("2026-10-05T19:00:00Z", DAKAR, NOW)).toBe("hier à 19 h");
    expect(seenWhen("2026-10-06T08:55:00Z", DAKAR, NOW)).toBe("aujourd’hui à 8 h 55");
    expect(seenWhen("2026-10-01T08:55:00Z", DAKAR, NOW)).toBe("le 1er octobre");
  });

  it("date une ligne d'historique", () => {
    expect(historyWhen("2026-10-05T17:12:00Z", DAKAR, NOW)).toBe("Hier, 17 h 12");
    expect(historyWhen("2026-10-06T08:55:00Z", DAKAR, NOW)).toBe("Aujourd'hui, 8 h 55");
    expect(historyWhen("2026-09-30T20:41:00Z", DAKAR, NOW)).toBe("30 septembre, 20 h 41");
  });
});

describe("contact d'une personne ajoutée", () => {
  it("reconnaît un e-mail ou neuf chiffres", () => {
    expect(contactOf(" awa@example.com ")).toEqual({ email: "awa@example.com" });
    expect(contactOf("77 123 45 67")).toEqual({ phone: "771234567" });
    expect(contactOf("+221 77 123 45 67")).toEqual({ phone: "771234567" });
  });

  it("refuse ce qui n'est ni l'un ni l'autre", () => {
    expect(contactOf("77 12")).toBeNull();
    expect(contactOf("awa@")).toBeNull();
    expect(contactOf("")).toBeNull();
  });
});

describe("grille « Qui peut faire quoi »", () => {
  const order = ["sell", "cancel_sale", "fix_stock", "collect_debt"];

  it("coche une ligne en gardant l'ordre de la grille", () => {
    expect(toggleAbility(order, ["collect_debt", "sell"], "fix_stock")).toEqual([
      "sell",
      "fix_stock",
      "collect_debt",
    ]);
  });

  it("décoche une ligne cochée", () => {
    expect(toggleAbility(order, ["sell", "collect_debt"], "sell")).toEqual(["collect_debt"]);
  });
});

describe("échéance d'un mot de passe provisoire (ADR 0078)", () => {
  const now = new Date("2026-10-17T10:00:00Z");

  it("dit le jour et l'heure dans le fuseau de l'entreprise", () => {
    expect(temporaryDeadline("2026-10-19T14:05:00Z", "Africa/Dakar", now)).toBe(
      "Expire le 19/10 à 14 h 05",
    );
  });

  it("dit « Expiré » une fois l'échéance passée", () => {
    expect(temporaryDeadline("2026-10-17T09:59:00Z", "Africa/Dakar", now)).toBe("Expiré");
  });
});
