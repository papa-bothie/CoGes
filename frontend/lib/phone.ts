/**
 * Téléphone au format du Sénégal (lot 1) : « +221 » affiché devant le champ, neuf chiffres
 * groupés « 77 000 00 00 ». Le numéro s'enregistre sans indicatif, comme il se lit.
 */
const DIGITS = 9;

/** Chiffres tapés, sans indicatif ni séparateurs, neuf au plus. */
export function phoneDigits(raw: string): string {
  let digits = raw.replace(/\D/g, "");
  if (digits.length > DIGITS && digits.startsWith("221")) digits = digits.slice(3);
  return digits.slice(0, DIGITS);
}

/** « 776559021 » → « 77 655 90 21 », au fil de la frappe. */
export function formatPhone(raw: string): string {
  const digits = phoneDigits(raw);
  return [digits.slice(0, 2), digits.slice(2, 5), digits.slice(5, 7), digits.slice(7, 9)]
    .filter(Boolean)
    .join(" ");
}

/** Vide (facultatif) ou neuf chiffres. */
export function isCompletePhone(raw: string): boolean {
  const length = phoneDigits(raw).length;
  return length === 0 || length === DIGITS;
}
