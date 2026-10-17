import { describe, expect, it } from "vitest";

import { resolveBack, withFrom } from "@/lib/back-target";

const MONEY = { href: "/finance", label: "L'argent" };
const CUSTOMER = "5b7c2b0e-8f3a-4d1e-9c2a-1f0e3d4c5b6a";

describe("resolveBack", () => {
  it("revient à l'écran parent sans `from`", () => {
    expect(resolveBack(null, MONEY)).toEqual(MONEY);
    expect(resolveBack("", MONEY)).toEqual(MONEY);
  });

  it.each([
    "https://evil.example/finance",
    "//evil.example",
    "/\\evil.example",
    "/.//evil.example",
    "javascript:alert(1)",
    "/login",
    "/login?next=/finance",
  ])("refuse un `from` qui quitte CoGes ou mène à la connexion : %s", (from) => {
    expect(resolveBack(from, MONEY)).toEqual(MONEY);
  });

  it("nomme la personne quand sa fiche est déjà lue", () => {
    const target = resolveBack(`/customers/${CUSTOMER}`, MONEY, ({ kind, id }) =>
      kind === "customer" && id === CUSTOMER ? "Moussa Fall" : undefined,
    );
    expect(target).toEqual({ href: `/customers/${CUSTOMER}`, label: "Moussa Fall" });
  });

  it("dit « Fiche du client » quand le nom n'est pas connu", () => {
    expect(resolveBack(`/customers/${CUSTOMER}`, MONEY).label).toBe("Fiche du client");
  });

  it("nomme la vente par son numéro court", () => {
    const target = resolveBack(`/sales/${CUSTOMER}`, MONEY, () => "V-001044");
    expect(target.label).toBe("Vente n° 1044");
    expect(resolveBack(`/sales/${CUSTOMER}`, MONEY).label).toBe("La vente");
  });

  it.each([
    ["/dashboard", "Accueil"],
    ["/finance", "L'argent"],
    ["/products", "Stock"],
    ["/insights", "Conseils"],
    ["/notifications", "Alertes"],
  ])("nomme la rubrique %s", (from, label) => {
    expect(resolveBack(from, MONEY)).toEqual({ href: from, label });
  });

  it("garde la requête de l'origine et dit « Retour » pour une page sans nom", () => {
    expect(resolveBack("/products/categories", MONEY)).toEqual({
      href: "/products/categories",
      label: "Retour",
    });
    expect(resolveBack("/insights?type=stockout_risk", MONEY).href).toBe(
      "/insights?type=stockout_risk",
    );
  });
});

describe("withFrom", () => {
  it("ajoute l'origine sans perdre la requête", () => {
    expect(withFrom(`/finance/collect?customer=${CUSTOMER}`, `/customers/${CUSTOMER}`)).toBe(
      `/finance/collect?customer=${CUSTOMER}&from=%2Fcustomers%2F${CUSTOMER}`,
    );
    expect(withFrom("/finance/cash", "/insights")).toBe("/finance/cash?from=%2Finsights");
  });

  it("aller-retour : le `from` posé se relit", () => {
    const href = withFrom("/inventory/receive", "/insights");
    const from = new URLSearchParams(href.split("?")[1]).get("from");
    expect(resolveBack(from, MONEY)).toEqual({ href: "/insights", label: "Conseils" });
  });
});
