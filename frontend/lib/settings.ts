/**
 * Réglages, maquette v2 (écrans 24b et 24d, ADR 0075) : les moments en mots et le contact
 * d'une personne ajoutée.
 */
import { formatClock, formatDate, formatDayMonth } from "@/lib/format";
import { labels } from "@/lib/labels";
import { addDays, todayIn } from "@/lib/period";
import { phoneDigits } from "@/lib/phone";

/** « 19 h 00 » → « 19 h », comme la maquette ; « 9 h 05 » reste tel quel. */
export function shortClock(value: string, timeZone: string): string {
  return formatClock(value, timeZone).replace(/ h 00$/, " h");
}

/** « aujourd’hui à 8 h 55 », « hier à 19 h », sinon « le 3 octobre ». */
export function seenWhen(value: string, timeZone: string, now: Date = new Date()): string {
  const today = todayIn(timeZone, now);
  const day = todayIn(timeZone, new Date(value));
  if (day === today) return `aujourd’hui à ${shortClock(value, timeZone)}`;
  if (day === addDays(today, -1)) return `hier à ${shortClock(value, timeZone)}`;
  return `le ${formatDayMonth(value, timeZone)}`;
}

/** Moment d'une ligne d'historique : « Aujourd'hui, 8 h 55 », « Hier, 17 h 12 », « 3 octobre, 11 h 30 ». */
export function historyWhen(value: string, timeZone: string, now: Date = new Date()): string {
  const today = todayIn(timeZone, now);
  const day = todayIn(timeZone, new Date(value));
  const clock = formatClock(value, timeZone);
  if (day === today) return `Aujourd'hui, ${clock}`;
  if (day === addDays(today, -1)) return `Hier, ${clock}`;
  return `${formatDayMonth(value, timeZone)}, ${clock}`;
}

/** Échéance d'un mot de passe provisoire (ADR 0078) : « Expire le 19/10 à 14 h 05 » ou « Expiré ». */
export function temporaryDeadline(until: string, timeZone: string, now: Date = new Date()): string {
  const t = labels.settingsScreens.people;
  if (new Date(until).getTime() <= now.getTime()) return t.expired;
  return t.expires(formatDate(until, timeZone).slice(0, 5), formatClock(until, timeZone));
}

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** « Téléphone ou e-mail » : un e-mail s'il a un « @ », sinon neuf chiffres ; `null` si illisible. */
export function contactOf(raw: string): { email: string } | { phone: string } | null {
  const text = raw.trim();
  if (text.includes("@")) return EMAIL.test(text) ? { email: text } : null;
  const digits = phoneDigits(text);
  return digits.length === 9 ? { phone: digits } : null;
}

/** Coche ou décoche une ligne de la grille ; les lignes gardent l'ordre de la grille. */
export function toggleAbility(
  order: readonly string[],
  checked: readonly string[],
  key: string,
): string[] {
  const next = new Set(checked);
  if (next.has(key)) next.delete(key);
  else next.add(key);
  return order.filter((item) => next.has(item));
}
