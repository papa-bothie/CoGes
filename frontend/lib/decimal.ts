/**
 * Comparaison de décimaux reçus en chaîne, **sans** `float` : mise à l'échelle en
 * `BigInt`. Sert au confort d'affichage (griser un bouton, plafonner une saisie) ; le
 * serveur reste juge de chaque règle.
 */

const DECIMAL = /^([+-])?(\d*)(?:\.(\d*))?$/;

function scaled(value: string, digits: number): bigint | null {
  const match = DECIMAL.exec(value.trim().replace(",", "."));
  if (!match || (match[2] === "" && (match[3] ?? "") === "")) return null;
  const fraction = (match[3] ?? "").padEnd(digits, "0").slice(0, digits);
  const magnitude = BigInt(`${match[2] || "0"}${fraction}`);
  return match[1] === "-" ? -magnitude : magnitude;
}

function fractionDigits(value: string): number {
  const dot = value.replace(",", ".").indexOf(".");
  return dot === -1 ? 0 : value.length - dot - 1;
}

/** Signe de `a - b` (-1, 0, 1), ou `null` si l'une des deux n'est pas un décimal. */
export function compareDecimal(a: string, b: string): -1 | 0 | 1 | null {
  const digits = Math.max(fractionDigits(a), fractionDigits(b));
  const left = scaled(a, digits);
  const right = scaled(b, digits);
  if (left === null || right === null) return null;
  return left < right ? -1 : left > right ? 1 : 0;
}

/** Saisie utilisateur → décimal pour l'API (« 1,5 » → « 1.5 »), ou `null` si illisible. */
export function parseDecimalInput(value: string): string | null {
  const normalized = value.trim().replace(/\s/g, "").replace(",", ".");
  return /^\d+(\.\d+)?$/.test(normalized) ? normalized : null;
}

/** Décimal de l'API → valeur de champ lisible (« 12.500 » → « 12,5 », « 3.000 » → « 3 »). */
export function toInputDecimal(value: string): string {
  if (!value.includes(".")) return value;
  return value.replace(/\.?0+$/, "").replace(".", ",");
}

/**
 * `a - b` en chaîne, sans `float` — pour **afficher** un reste (« retournable »), jamais
 * pour décider : le serveur borne la saisie de toute façon. `null` si illisible.
 */
export function subtractDecimal(a: string, b: string): string | null {
  const digits = Math.max(fractionDigits(a), fractionDigits(b));
  const left = scaled(a, digits);
  const right = scaled(b, digits);
  if (left === null || right === null) return null;
  const diff = left - right;
  const negative = diff < 0n;
  const text = (negative ? -diff : diff).toString().padStart(digits + 1, "0");
  const integer = text.slice(0, text.length - digits);
  const fraction = digits ? `.${text.slice(text.length - digits)}` : "";
  return `${negative ? "-" : ""}${integer}${fraction}`;
}

/** `a + b` en chaîne, sans `float` (somme affichée d'une semaine de ventes). */
export function addDecimal(a: string, b: string): string | null {
  const negated = b.trim().startsWith("-") ? b.trim().slice(1) : `-${b.trim()}`;
  return subtractDecimal(a, negated);
}

/** Somme d'une liste de décimaux, « 0 » pour une liste vide ; `null` si l'un est illisible. */
export function sumDecimals(values: readonly string[]): string | null {
  let total: string | null = "0";
  for (const value of values) {
    if (total === null) return null;
    total = addDecimal(total, value);
  }
  return total;
}

/**
 * Taux saisi en pourcentage (« 18 », « 5,5 ») → fraction pour l'API (« 0.18 », « 0.055 »),
 * par décalage de la virgule sur la chaîne, sans `float`. `null` si illisible.
 */
export function percentToRate(value: string): string | null {
  const parsed = parseDecimalInput(value);
  if (parsed === null) return null;
  const [integer = "0", fraction = ""] = parsed.split(".");
  const digits = integer.padStart(3, "0");
  const head = digits.slice(0, -2).replace(/^0+(?=\d)/, "");
  const rate = `${head}.${digits.slice(-2)}${fraction}`.replace(/0+$/, "").replace(/\.$/, "");
  return rate === "" ? "0" : rate;
}

/** Fraction de l'API (« 0.1800 ») → pourcentage affichable (« 18 », « 5,5 »). */
export function rateToPercent(value: string): string {
  const [integer = "0", fraction = ""] = value.split(".");
  const shifted = `${integer}${fraction.padEnd(2, "0")}`;
  const whole = shifted.slice(0, integer.length + 2).replace(/^0+(?=\d)/, "");
  const rest = shifted.slice(integer.length + 2).replace(/0+$/, "");
  return rest ? `${whole},${rest}` : whole;
}
