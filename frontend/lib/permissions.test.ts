import { describe, expect, it } from "vitest";

import { ADVICE_NAV, isActive, MAIN_NAV } from "./navigation";
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

describe("navigation de la maquette v2", () => {
  const MANAGER = [...SALESPERSON, ...ACCOUNTANT, "products:create", "sales:create"];
  const hrefs = (permissions: string[]) =>
    filterByPermission(MAIN_NAV, permissions).map((item) => item.label);

  it("cinq entrées pour le gérant, dans l'ordre de la maquette", () => {
    expect(hrefs(MANAGER)).toEqual(["Accueil", "Vendre", "Stock", "Clients", "Argent"]);
    expect(can(MANAGER, ADVICE_NAV.permission)).toBe(true);
  });

  it("le vendeur ne voit que Accueil, Vendre et Clients", () => {
    expect(hrefs(SALESPERSON)).toEqual(["Accueil", "Vendre", "Clients"]);
    expect(can(SALESPERSON, ADVICE_NAV.permission)).toBe(false);
  });

  it("une rubrique s'allume sur ses pages provisoires", () => {
    const [, sell, stock, clients] = MAIN_NAV;
    expect(isActive("/sales/123/receipt", sell!)).toBe(true);
    expect(isActive("/inventory", stock!)).toBe(true);
    expect(isActive("/suppliers/9", clients!)).toBe(true);
    expect(isActive("/analytics", ADVICE_NAV)).toBe(true);
    expect(isActive("/salesman", sell!)).toBe(false);
  });
});
