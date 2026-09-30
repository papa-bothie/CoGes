import { Badge } from "@/components/ui/badge";
import type { Schemas } from "@/lib/api/schema";
import { labels } from "@/lib/labels";

type SaleStatus = Schemas["SaleStatus"];
type StockStatus = Schemas["StockStatus"];

const SALE_VARIANTS = {
  draft: "neutral",
  confirmed: "info",
  cancelled: "danger",
} as const;

/**
 * Statut d'une vente. « Retournée » n'est pas un statut de la base : c'est une vente
 * confirmée qui porte au moins un retour (`has_returns`), et le badge le dit.
 */
export function SaleStatusBadge({
  status,
  hasReturns,
}: {
  status: SaleStatus;
  hasReturns: boolean;
}) {
  if (status === "confirmed" && hasReturns) {
    return <Badge variant="warning">{labels.sales.status.returned}</Badge>;
  }
  return <Badge variant={SALE_VARIANTS[status]}>{labels.sales.status[status]}</Badge>;
}

const STOCK_VARIANTS = { ok: "success", low: "warning", out: "danger" } as const;

/** Statut de stock calculé par l'API (`ok`, `low`, `out`). */
export function StockStatusBadge({ status }: { status: StockStatus }) {
  return <Badge variant={STOCK_VARIANTS[status]}>{labels.stock.status[status]}</Badge>;
}
