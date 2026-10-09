/**
 * Montant en toutes lettres, pour la facture A4 de la maquette v2 (05b) : « Arrêtée la
 * présente facture à la somme de vingt-cinq mille francs CFA ». Orthographe traditionnelle
 * (traits d'union sous cent, « et » pour 21 à 71, « quatre-vingts », « cents » final), en
 * `bigint` : jamais de flottant sur un montant.
 */
const UNITS = [
  "zéro",
  "un",
  "deux",
  "trois",
  "quatre",
  "cinq",
  "six",
  "sept",
  "huit",
  "neuf",
  "dix",
  "onze",
  "douze",
  "treize",
  "quatorze",
  "quinze",
  "seize",
];
const TENS = ["", "dix", "vingt", "trente", "quarante", "cinquante", "soixante"];

function belowHundred(value: number, final: boolean): string {
  if (value <= 16) return UNITS[value]!;
  if (value < 20) return `dix-${UNITS[value - 10]}`;
  if (value < 70) {
    const tens = Math.floor(value / 10);
    const unit = value % 10;
    if (unit === 0) return TENS[tens]!;
    return unit === 1 ? `${TENS[tens]} et un` : `${TENS[tens]}-${UNITS[unit]}`;
  }
  if (value < 80) {
    return value === 71 ? "soixante et onze" : `soixante-${belowHundred(value - 60, final)}`;
  }
  // 80 à 99 : « quatre-vingts » seul en fin de nombre, sans « s » sinon.
  if (value === 80) return final ? "quatre-vingts" : "quatre-vingt";
  return `quatre-vingt-${belowHundred(value - 80, final)}`;
}

function belowThousand(value: number, final: boolean): string {
  const hundreds = Math.floor(value / 100);
  const rest = value % 100;
  const parts: string[] = [];
  if (hundreds > 0) {
    const plural = hundreds > 1 && rest === 0 && final;
    parts.push(hundreds === 1 ? "cent" : `${UNITS[hundreds]} cent${plural ? "s" : ""}`);
  }
  if (rest > 0 || hundreds === 0) parts.push(belowHundred(rest, final));
  return parts.join(" ");
}

const SCALES: [bigint, string][] = [
  [1_000_000_000n, "milliard"],
  [1_000_000n, "million"],
];

/** Un entier positif en toutes lettres : `numberInWords(25000n)` → « vingt-cinq mille ». */
export function numberInWords(value: bigint): string {
  if (value === 0n) return UNITS[0]!;
  const parts: string[] = [];
  let rest = value;
  for (const [scale, name] of SCALES) {
    const count = rest / scale;
    if (count > 0n) {
      parts.push(`${numberInWords(count)} ${name}${count > 1n ? "s" : ""}`);
      rest %= scale;
    }
  }
  const thousands = Number(rest / 1000n);
  const units = Number(rest % 1000n);
  // « mille » est invariable et ne prend pas « un » devant ; les cents qui le précèdent
  // ne prennent pas de « s » (« deux cent mille »).
  if (thousands > 0)
    parts.push(thousands === 1 ? "mille" : `${belowThousand(thousands, false)} mille`);
  if (units > 0) parts.push(belowThousand(units, true));
  return parts.join(" ");
}

/** Montant de l'API (« 25000.00 ») en francs CFA : « vingt-cinq mille francs CFA ». */
export function amountInWords(value: string): string {
  const whole = BigInt(value.split(".")[0]?.replace(/\D/g, "") || "0");
  return `${numberInWords(whole)} franc${whole > 1n ? "s" : ""} CFA`;
}
