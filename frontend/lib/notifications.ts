/**
 * Où mène une notification : vers l'**élément** concerné quand `data` porte son
 * identifiant (produit, vente, insight), sinon vers l'écran qui permet d'agir.
 */
import type { Schemas } from "@/lib/api/schema";
import { labels } from "@/lib/labels";

export type AppNotification = Schemas["NotificationRead"];

const UUID = /^[0-9a-f-]{36}$/i;

function id(data: Record<string, unknown>, key: string): string | null {
  const value = data[key];
  return typeof value === "string" && UUID.test(value) ? value : null;
}

export function notificationHref(notification: Pick<AppNotification, "type" | "data">): string {
  const data = notification.data as Record<string, unknown>;
  switch (notification.type) {
    case "stock_low":
    case "stock_out": {
      // « Commander » : la livraison s'ouvre avec l'article déjà sur la liste (ADR 0071).
      const product = id(data, "product_id");
      return product ? `/inventory/receive?product=${product}` : "/inventory/receive";
    }
    case "sale_cancelled": {
      const sale = id(data, "sale_id");
      return sale ? `/sales/${sale}` : "/sales?status=cancelled";
    }
    case "debt_due": {
      // Depuis le lot 3e, l'alerte porte la personne (ADR 0074) ; avant, la liste des
      // dettes échues.
      const party = id(data, "party_id");
      if (!party) return "/finance/debts?overdue=1";
      return data.party_type === "supplier"
        ? `/finance/pay?supplier=${party}`
        : `/finance/collect?customer=${party}`;
    }
    case "insight_critical": {
      const type = typeof data.insight_type === "string" ? data.insight_type : null;
      return type ? `/insights?type=${encodeURIComponent(type)}` : "/insights";
    }
    case "forecast_alert":
      return "/insights?view=forecasts";
    case "login_failures":
      // Échecs de connexion répétés (ADR 0078) : là où l'on redonne un mot de passe.
      return "/settings/people";
    default:
      return "/notifications";
  }
}

export type AlertTone = "stock" | "depenses" | "argent" | "clients" | "neutre" | "conseils";

/**
 * Couleur, icône et action directe de chaque alerte (maquette v2, écran 23, ADR 0074) :
 * rupture en rouge, stock bas en orange, fournisseur à payer en bleu, client en retard en
 * violet, vente annulée en gris foncé.
 */
export function alertLook(notification: Pick<AppNotification, "type" | "data">): {
  tone: AlertTone;
  action: string;
} {
  const data = notification.data as Record<string, unknown>;
  const t = labels.alerts.actions;
  switch (notification.type) {
    case "stock_low":
      return { tone: "stock", action: t.order };
    case "stock_out":
      return { tone: "depenses", action: t.order };
    case "debt_due":
      return data.party_type === "supplier"
        ? { tone: "argent", action: t.pay }
        : { tone: "clients", action: t.collect };
    case "sale_cancelled":
      return { tone: "neutre", action: t.sale };
    case "login_failures":
      return { tone: "stock", action: t.people };
    default:
      return { tone: "conseils", action: t.advice };
  }
}
