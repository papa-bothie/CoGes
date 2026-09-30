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

/**
 * Quantité suivie de son unité accordée : « 1 pièce », « 7 pièces », « 1,5 litre »
 * (le pluriel commence à 2, règle du français), « 2,5 kg ».
 */
export function formatQtyWithUnit(
  value: string | null | undefined,
  singular: string,
  plural: string,
): string {
  const qty = formatQty(value);
  if (qty === "—") return qty;
  const integer = (value ?? "").replace(/^-/, "").split(".")[0] ?? "0";
  return `${qty} ${BigInt(integer || "0") >= 2n ? plural : singular}`;
}
