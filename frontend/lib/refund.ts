/**
 * Valeur rendue d'un retour, affichée pendant la saisie (maquette 06). Même formule que le
 * serveur (`_refund_amounts`, § 4.7, ADR 0026) : remise proratisée, net et taxe arrondis
 * **séparément** au centime, puis additionnés ; un retour total rend `line_total`. Le
 * serveur reste juge : le montant enregistré est le sien. Calcul en `bigint`, sans float.
 */
const DECIMAL = /^(-)?(\d+)(?:\.(\d+))?$/;

function scaled(value: string, digits: number): bigint {
  const match = DECIMAL.exec(value.trim());
  if (!match) return 0n;
  const fraction = (match[3] ?? "").padEnd(digits, "0").slice(0, digits);
  const magnitude = BigInt(`${match[2]}${fraction}`);
  return match[1] ? -magnitude : magnitude;
}

/** Division arrondie au plus proche, moitié vers le haut (ROUND_HALF_UP, positifs). */
function roundDiv(value: bigint, divisor: bigint): bigint {
  return (value * 2n + divisor) / (divisor * 2n);
}

type Line = { qty: string; unit_price: string; discount: string; tax_rate: string };

/** Remboursable TTC, en centimes, de `returned` unités d'une ligne vendue. */
export function refundCents(line: Line, returned: string): bigint {
  const q = scaled(returned, 3);
  const sold = scaled(line.qty, 3);
  if (q <= 0n || sold <= 0n) return 0n;
  // Net avant taxe à l'échelle 1e5 : prix (1e2) × quantité (1e3).
  const gross = q * scaled(line.unit_price, 2);
  const discount = (scaled(line.discount, 2) * q * 1000n) / sold;
  const net = gross - discount;
  const netCents = roundDiv(net, 1000n);
  const taxCents = roundDiv(net * scaled(line.tax_rate, 4), 10_000_000n);
  return netCents + taxCents;
}

/** Centimes → chaîne décimale de l'API (« 2800.00 »). */
export function centsToAmount(cents: bigint): string {
  const text = cents.toString().padStart(3, "0");
  return `${text.slice(0, -2)}.${text.slice(-2)}`;
}
