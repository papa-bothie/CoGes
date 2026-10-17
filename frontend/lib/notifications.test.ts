import { describe, expect, it } from "vitest";

import { alertLook, notificationHref, type AppNotification } from "./notifications";

const ID = "11111111-2222-3333-4444-555555555555";
const alert = (type: AppNotification["type"], data: Record<string, unknown>) =>
  ({ type, data }) as Pick<AppNotification, "type" | "data">;

describe("alertes (écran 23)", () => {
  it("donnent une action directe à chaque type", () => {
    expect(alertLook(alert("stock_low", {}))).toEqual({ tone: "stock", action: "Commander" });
    expect(alertLook(alert("stock_out", {}))).toEqual({ tone: "depenses", action: "Commander" });
    expect(alertLook(alert("debt_due", { party_type: "supplier" }))).toEqual({
      tone: "argent",
      action: "Payer",
    });
    expect(alertLook(alert("debt_due", { party_type: "customer" }))).toEqual({
      tone: "clients",
      action: "Encaisser",
    });
    expect(alertLook(alert("sale_cancelled", {})).action).toBe("Voir la vente");
  });

  it("mènent là où l'on agit", () => {
    expect(notificationHref(alert("stock_low", { product_id: ID }))).toBe(
      `/inventory/receive?product=${ID}&from=%2Fnotifications`,
    );
    expect(notificationHref(alert("debt_due", { party_type: "supplier", party_id: ID }))).toBe(
      `/finance/pay?supplier=${ID}&from=%2Fnotifications`,
    );
    expect(notificationHref(alert("debt_due", { party_type: "customer", party_id: ID }))).toBe(
      `/finance/collect?customer=${ID}&from=%2Fnotifications`,
    );
    expect(notificationHref(alert("login_failures", { user_id: ID }))).toBe("/settings/people");
    expect(alertLook(alert("login_failures", { user_id: ID }))).toEqual({
      tone: "stock",
      action: "Voir les personnes",
    });
    // Une alerte d'avant le lot 3e, sans la personne : la liste des dettes échues.
    expect(notificationHref(alert("debt_due", { party_type: "customer" }))).toBe(
      "/finance/debts?overdue=1",
    );
    expect(notificationHref(alert("sale_cancelled", { sale_id: ID }))).toBe(`/sales/${ID}`);
  });
});
