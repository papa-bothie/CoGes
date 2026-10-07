import { Badge } from "@/components/ui/badge";
import type { Schemas } from "@/lib/api/schema";
import { compareDecimal } from "@/lib/decimal";
import { formatMoney } from "@/lib/format";
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

/**
 * Ce qui reste à payer sur une vente confirmée (ADR 0062) : « Payé » ou « Reste X ».
 * Le reste suit la dette de la vente, règlements et compensations compris. Une dette
 * abandonnée n'est plus réclamée : elle se dit, en gris, plutôt qu'un reste orange.
 * Rien pour un brouillon ou une vente annulée.
 */
export function SalePaymentBadge({
  sale,
  currency,
}: {
  sale: Pick<Schemas["SaleRead"], "status" | "balance" | "debt_status">;
  currency?: string;
}) {
  if (sale.status !== "confirmed") return null;
  if (sale.debt_status === "written_off") {
    return <Badge variant="neutral">{labels.sales.payment.writtenOff}</Badge>;
  }
  if (compareDecimal(sale.balance, "0") === 1) {
    return (
      <Badge variant="warning" className="numeric">
        {labels.sales.payment.remaining(formatMoney(sale.balance, currency))}
      </Badge>
    );
  }
  return <Badge variant="success">{labels.sales.payment.paid}</Badge>;
}

const STOCK_VARIANTS = { ok: "success", low: "warning", out: "danger" } as const;

/** Statut de stock calculé par l'API (`ok`, `low`, `out`). */
export function StockStatusBadge({ status }: { status: StockStatus }) {
  return <Badge variant={STOCK_VARIANTS[status]}>{labels.stock.status[status]}</Badge>;
}
