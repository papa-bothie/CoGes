/**
 * Où mène une notification : vers l'**élément** concerné quand `data` porte son
 * identifiant (produit, vente, insight), sinon vers l'écran qui permet d'agir.
 */
import type { Schemas } from "@/lib/api/schema";

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
      const product = id(data, "product_id");
      return product ? `/products/${product}` : "/inventory";
    }
    case "sale_cancelled": {
      const sale = id(data, "sale_id");
      return sale ? `/sales/${sale}` : "/sales?status=cancelled";
    }
    case "debt_due":
      // Pas d'identifiant de tiers dans l'alerte : la liste des dettes échues.
      return "/finance?tab=debts&overdue=1";
    case "insight_critical": {
      const type = typeof data.insight_type === "string" ? data.insight_type : null;
      return type ? `/insights?status=all&type=${encodeURIComponent(type)}` : "/insights";
    }
    case "forecast_alert":
      return "/insights?tab=forecasts";
    default:
      return "/notifications";
  }
}
