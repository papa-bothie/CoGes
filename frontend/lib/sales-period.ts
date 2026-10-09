import { addDays } from "@/lib/period";

/** Les puces de période de la liste des ventes (maquette 03). */
export const SALES_PERIODS = ["today", "yesterday", "week", "month"] as const;
export type SalesPeriod = (typeof SALES_PERIODS)[number];

export function isSalesPeriod(value: string | null): value is SalesPeriod {
  return value !== null && (SALES_PERIODS as readonly string[]).includes(value);
}

/**
 * Bornes calendaires d'une période, `today` étant le jour courant dans le fuseau de
 * l'entreprise. « Cette semaine » commence le lundi, comme un commerçant la compte.
 */
export function salesPeriodDays(period: SalesPeriod, today: string): { from: string; to: string } {
  switch (period) {
    case "today":
      return { from: today, to: today };
    case "yesterday": {
      const yesterday = addDays(today, -1);
      return { from: yesterday, to: yesterday };
    }
    case "week": {
      const weekday = new Date(`${today}T12:00:00Z`).getUTCDay();
      return { from: addDays(today, -((weekday + 6) % 7)), to: today };
    }
    case "month":
      return { from: `${today.slice(0, 8)}01`, to: today };
  }
}
