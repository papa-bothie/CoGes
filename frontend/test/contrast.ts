/** Luminance relative et contraste WCAG 2 d'une couleur `#rrggbb` (tests seulement). */
function channel(value: number): number {
  const c = value / 255;
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

export function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((start) => parseInt(hex.slice(start, start + 2), 16));
  return 0.2126 * channel(r!) + 0.7152 * channel(g!) + 0.0722 * channel(b!);
}

export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi! + 0.05) / (lo! + 0.05);
}

/** Le gris qu'une imprimante noir et blanc tire d'une couleur (même luminance). */
export function grey(hex: string): string {
  const level = Math.round(luminance(hex) ** (1 / 2.2) * 255)
    .toString(16)
    .padStart(2, "0");
  return `#${level}${level}${level}`;
}
