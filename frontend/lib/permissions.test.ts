import { describe, expect, it } from "vitest";

import { NAV_ITEMS, pageTitle } from "./navigation";
import { can, filterByPermission } from "./permissions";

// Extraits de la matrice RBAC (ADR 0007).
const SALESPERSON = [
  "categories:read",
  "customers:create",
  "customers:read",
  "dashboard:read",
  "inventory:read",
  "notifications:read",
  "payments:create",
  "payments:read",
  "products:read",
  "sales:confirm",
  "sales:read",
  "suppliers:read",
];
const ACCOUNTANT = [
  "analytics:read",
  "audit:read",
  "company:read",
  "dashboard:read",
  "debts:read",
  "expenses:read",
  "insights:read",
  "payments:read",
  "sales:read",
];

describe("can", () => {
  it("vérifie un code simple", () => {
    expect(can(SALESPERSON, "sales:confirm")).toBe(true);
    expect(can(SALESPERSON, "sales:cancel")).toBe(false);
  });

  it("accepte l'un des codes d'une liste", () => {
    expect(can(ACCOUNTANT, { anyOf: ["users:read", "company:read"] })).toBe(true);
    expect(can(SALESPERSON, { anyOf: ["users:read", "company:read"] })).toBe(false);
  });

  it("refuse tout tant que les permissions sont inconnues", () => {
    expect(can(undefined, "dashboard:read")).toBe(false);
  });

  it("laisse passer une entrée sans règle", () => {
    expect(can([], undefined)).toBe(true);
  });
});

describe("navigation filtrée", () => {
  const hrefs = (permissions: string[]) =>
    filterByPermission(NAV_ITEMS, permissions).map((item) => item.href);

  it("garde l'ordre du prototype pour le vendeur, sans Finance ni Paramètres", () => {
    expect(hrefs(SALESPERSON)).toEqual([
      "/dashboard",
      "/sales",
      "/inventory",
      "/products",
      "/customers",
      "/suppliers",
      "/finance",
    ]);
  });

  it("montre Finance, Analytics, Intelligence et Paramètres au comptable", () => {
    expect(hrefs(ACCOUNTANT)).toEqual([
      "/dashboard",
      "/sales",
      "/finance",
      "/analytics",
      "/insights",
      "/settings",
    ]);
  });
});

describe("pageTitle", () => {
  it("prend l'entrée de navigation la plus précise", () => {
    expect(pageTitle("/sales")).toBe("Ventes");
    expect(pageTitle("/sales/new")).toBe("Ventes");
    expect(pageTitle("/notifications")).toBe("Notifications");
    expect(pageTitle("/inconnu")).toBe("CoGes");
  });
});
