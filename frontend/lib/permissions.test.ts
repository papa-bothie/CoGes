import { describe, expect, it } from "vitest";

import { ADVICE_NAV, isActive, MAIN_NAV, resolveNav, SETTINGS_NAV, visibleNav } from "./navigation";
import { can } from "./permissions";

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

describe("can : tous les droits", () => {
  it("exige chacun des codes de `allOf`", () => {
    expect(can(ACCOUNTANT, { allOf: ["debts:read", "payments:read"] })).toBe(true);
    expect(can(ACCOUNTANT, { allOf: ["debts:read", "payments:create"] })).toBe(false);
  });
});

describe("navigation de la maquette v2 (ADR 0099)", () => {
  const MANAGER = [...SALESPERSON, ...ACCOUNTANT, "products:create", "sales:create"];
  const labelsFor = (permissions: string[]) =>
    visibleNav(MAIN_NAV, permissions).map((item) => item.label);
  const hrefOf = (label: string, permissions: string[]) =>
    visibleNav(MAIN_NAV, permissions).find((item) => item.label === label)?.href;

  it("cinq entrées pour le gérant, dans l'ordre de la maquette", () => {
    expect(labelsFor(MANAGER)).toEqual(["Accueil", "Vendre", "Stock", "Clients", "Argent"]);
    expect(resolveNav(ADVICE_NAV, MANAGER)?.href).toBe("/insights");
  });

  it("le vendeur voit le stock qu'il lit, ni l'argent ni les conseils", () => {
    expect(labelsFor(SALESPERSON)).toEqual(["Accueil", "Vendre", "Stock", "Clients"]);
    expect(resolveNav(ADVICE_NAV, SALESPERSON)).toBeNull();
  });

  it("chaque entrée s'ouvre sur un écran permis, jamais par un droit voisin", () => {
    // Sans `sales:create`, « Vendre » mène à l'historique, pas à la caisse.
    expect(hrefOf("Vendre", ACCOUNTANT)).toBe("/sales");
    expect(hrefOf("Vendre", [...ACCOUNTANT, "sales:create"])).toBe("/sales/new");
    // Comptable à qui il ne reste que « Encaisser une dette » : Argent ouvre les dettes.
    expect(hrefOf("Argent", ["dashboard:read", "debts:read", "payments:create"])).toBe(
      "/finance/debts",
    );
    // `analytics:read` ne donne plus Stock, `debts:read` ne donne plus le compte d'argent.
    expect(labelsFor(["dashboard:read", "analytics:read"])).toEqual(["Accueil", "Argent"]);
    expect(resolveNav(ADVICE_NAV, ["analytics:read"])).toBeNull();
    // Réglages : la première page permise.
    expect(resolveNav(SETTINGS_NAV[0]!, ["audit:read"])?.href).toBe("/settings/history");
    expect(resolveNav(SETTINGS_NAV[0]!, SALESPERSON)).toBeNull();
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
