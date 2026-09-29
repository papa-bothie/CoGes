/**
 * Montants : l'API les envoie en **chaîne décimale** (jamais en nombre JSON). On les
 * formate sans passer par `number` : la partie entière est un `BigInt`, l'arrondi se fait
 * sur les chiffres. Aucun calcul métier ici — affichage uniquement.
 */

const DECIMAL = /^(-)?(\d+)(?:\.(\d+))?$/;

/** Décimales affichées par devise. XOF (FCFA) n'a pas de sous-unité. */
const CURRENCY_DIGITS: Record<string, number> = { XOF: 0, XAF: 0, GNF: 0 };

const CURRENCY_LABELS: Record<string, string> = { XOF: "FCFA", XAF: "FCFA" };

const NBSP = " ";

const integerFormatter = new Intl.NumberFormat("fr-FR", { useGrouping: true });

/** Arrondi « demi vers le haut » (loin de zéro), comme `ROUND_HALF_UP` côté serveur. */
function roundDigits(intPart: string, fraction: string, digits: number): [string, string] {
  const padded = fraction.padEnd(digits + 1, "0");
  const kept = padded.slice(0, digits);
  const next = Number(padded[digits] ?? "0");
  if (next < 5) return [intPart, kept];

  // Retenue sur la chaîne « entier + décimales conservées ».
  const combined = (BigInt(intPart + kept) + 1n).toString().padStart(intPart.length + digits, "0");
  const splitAt = combined.length - digits;
  return [combined.slice(0, splitAt), combined.slice(splitAt)];
}

export type DecimalParts = { negative: boolean; integer: string; fraction: string };

/** Découpe et arrondit une chaîne décimale ; `null` si elle est mal formée. */
export function decimalParts(value: string, digits: number): DecimalParts | null {
  const match = DECIMAL.exec(value.trim());
  if (!match) return null;
  const [, sign, rawInt = "0", rawFraction = ""] = match;
  const [integer, fraction] = roundDigits(rawInt, rawFraction, digits);
  const isZero = /^0*$/.test(integer) && /^0*$/.test(fraction);
  return { negative: sign === "-" && !isZero, integer, fraction };
}

/** « 1234567 » → « 1 234 567 » (espace fine insécable, séparateur fr-FR). */
export function groupDigits(integer: string): string {
  return integerFormatter.format(BigInt(integer));
}

export function currencyDigits(currency: string): number {
  return CURRENCY_DIGITS[currency] ?? 2;
}

export function currencyLabel(currency: string): string {
  return CURRENCY_LABELS[currency] ?? currency;
}

/**
 * `formatMoney("1234567.50")` → « 1 234 568 FCFA ».
 * Une valeur absente ou illisible s'affiche « — » plutôt qu'un nombre inventé.
 */
export function formatMoney(
  value: string | null | undefined,
  currency = "XOF",
  options: { withCurrency?: boolean } = {},
): string {
  if (value === null || value === undefined || value === "") return "—";
  const digits = currencyDigits(currency);
  const parts = decimalParts(value, digits);
  if (!parts) return "—";
  const amount =
    (parts.negative ? "-" : "") +
    groupDigits(parts.integer) +
    (digits > 0 ? `,${parts.fraction}` : "");
  return options.withCurrency === false ? amount : `${amount}${NBSP}${currencyLabel(currency)}`;
}
