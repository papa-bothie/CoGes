import type { PillStatus } from "@/components/kit/status-pill";
import type { Schemas } from "@/lib/api/schema";
import { compareDecimal } from "@/lib/decimal";
import { formatAmount } from "@/lib/format";

type SaleState = Pick<
  Schemas["SaleRead"],
  "status" | "balance" | "debt_status" | "has_returns" | "returned_total"
>;

/**
 * Pastille d'une vente (maquette v2, écrans 01, 03, 04) : « Annulée », « Dette abandonnée »
 * (écart du lot 0), « Reste 10 000 F », « Retour : 1 400 F » ou « Payé ». Un brouillon
 * n'en a pas. Le reste passe avant le retour : ce qui est encore dû compte d'abord.
 */
export function salePill(
  sale: SaleState,
  currency = "XOF",
): { status: PillStatus; amount?: string } | null {
  if (sale.status === "draft") return null;
  if (sale.status === "cancelled") return { status: "cancelled" };
  if (sale.debt_status === "written_off") return { status: "writtenOff" };
  if (compareDecimal(sale.balance, "0") === 1) {
    return { status: "remaining", amount: formatAmount(sale.balance, currency) };
  }
  if (sale.has_returns) {
    return { status: "returned", amount: formatAmount(sale.returned_total, currency) };
  }
  return { status: "paid" };
}
