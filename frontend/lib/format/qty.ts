import { decimalParts, groupDigits } from "./money";

/**
 * Quantités `numeric(14,3)`, reçues en chaîne : « 12.500 » → « 12,5 », « 1500.000 » →
 * « 1 500 ». Zéros inutiles retirés, trois décimales au plus.
 */
export function formatQty(value: string | null | undefined, unit?: string): string {
  if (value === null || value === undefined || value === "") return "—";
  const parts = decimalParts(value, 3);
  if (!parts) return "—";
  const fraction = parts.fraction.replace(/0+$/, "");
  const qty =
    (parts.negative ? "-" : "") + groupDigits(parts.integer) + (fraction ? `,${fraction}` : "");
  return unit ? `${qty} ${unit}` : qty;
}
