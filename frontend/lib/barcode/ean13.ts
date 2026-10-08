/**
 * Encodeur EAN-13 (norme GS1), pour l'étiquette imprimable d'un article (ADR 0066) : sans
 * bibliothèque ni service externe. Rend les 95 modules (1 = barre, 0 = espace), garde
 * centrale et gardes latérales comprises.
 */

/** Jeux L, G et R des chiffres 0 à 9, sur 7 modules. */
const L = [
  "0001101",
  "0011001",
  "0010011",
  "0111101",
  "0100011",
  "0110001",
  "0101111",
  "0111011",
  "0110111",
  "0001011",
];
const G = [
  "0100111",
  "0110011",
  "0011011",
  "0100001",
  "0011101",
  "0111001",
  "0000101",
  "0010001",
  "0001001",
  "0010111",
];
const R = [
  "1110010",
  "1100110",
  "1101100",
  "1000010",
  "1011100",
  "1001110",
  "1010000",
  "1000100",
  "1001000",
  "1110100",
];

/** Parité des six chiffres de gauche, choisie par le premier chiffre (qui n'est pas dessiné). */
const PARITY = [
  "LLLLLL",
  "LLGLGG",
  "LLGGLG",
  "LLGGGL",
  "LGLLGG",
  "LGGLLG",
  "LGGGLL",
  "LGLGLG",
  "LGLGGL",
  "LGGLGL",
];

/** Clé de contrôle des douze premiers chiffres : poids 1 et 3 en alternance. */
export function ean13CheckDigit(body: string): number {
  const total = [...body].reduce(
    (sum, digit, index) => sum + Number(digit) * (index % 2 ? 3 : 1),
    0,
  );
  return (10 - (total % 10)) % 10;
}

/** Treize chiffres dont la clé est juste. */
export function isValidEan13(code: string): boolean {
  return /^\d{13}$/.test(code) && ean13CheckDigit(code.slice(0, 12)) === Number(code[12]);
}

/** Les 95 modules d'un EAN-13 valide, ou `null`. */
export function ean13Modules(code: string): string | null {
  if (!isValidEan13(code)) return null;
  const digits = [...code].map(Number);
  const parity = PARITY[digits[0]!]!;
  let modules = "101";
  for (let index = 1; index <= 6; index += 1) {
    const set = parity[index - 1] === "L" ? L : G;
    modules += set[digits[index]!]!;
  }
  modules += "01010";
  for (let index = 7; index <= 12; index += 1) modules += R[digits[index]!]!;
  return `${modules}101`;
}
