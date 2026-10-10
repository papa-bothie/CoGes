import { formatDayLong, formatDayMonth } from "@/lib/format";
import { labels } from "@/lib/labels";
import { addDays, todayIn } from "@/lib/period";

const t = labels.peopleScreens;

/** Jours calendaires entre deux jours « 2026-10-06 » (b − a). */
function daysBetween(a: string, b: string): number {
  return Math.round((Date.parse(`${b}T12:00:00Z`) - Date.parse(`${a}T12:00:00Z`)) / 86_400_000);
}

/**
 * Les articles en quelques mots (maquette 14 et 16) : le premier mot de chaque nom, sans
 * doublon, le premier avec sa majuscule, les autres en minuscules : « Riz, huile, bougies ».
 */
export function shortNames(names: readonly string[]): string {
  const words: string[] = [];
  for (const name of names) {
    const word = name
      .trim()
      .split(/[\s,]+/)[0]
      ?.toLocaleLowerCase("fr-FR");
    if (word && !words.includes(word)) words.push(word);
  }
  const text = words.join(", ");
  return text.charAt(0).toLocaleUpperCase("fr-FR") + text.slice(1);
}

/** « Depuis 12 jours », « Depuis hier » : l'âge de la plus ancienne dette ouverte. */
export function sinceText(value: string, timeZone: string, now: Date = new Date()): string {
  return t.since(daysBetween(todayIn(timeZone, new Date(value)), todayIn(timeZone, now)));
}

/**
 * Quand, en mots : « aujourd'hui », « hier », le jour de la semaine dans les sept derniers
 * jours (« samedi »), puis « il y a 2 semaines », « il y a 3 mois ».
 */
export function agoText(value: string, timeZone: string, now: Date = new Date()): string {
  const today = todayIn(timeZone, now);
  const day = todayIn(timeZone, new Date(value));
  const days = daysBetween(day, today);
  if (days <= 0) return t.ago.today;
  if (days === 1) return t.ago.yesterday;
  if (days < 7) return formatDayLong(day).split(" ")[0]!.toLocaleLowerCase("fr-FR");
  if (days < 31) return t.ago.weeks(Math.max(1, Math.floor(days / 7)));
  return t.ago.months(Math.max(1, Math.floor(days / 30)));
}

/** « Aujourd'hui », « Hier », sinon « Samedi 3 octobre » (tuile « Dernière visite »). */
export function visitDay(value: string, timeZone: string, now: Date = new Date()): string {
  const today = todayIn(timeZone, now);
  const day = todayIn(timeZone, new Date(value));
  if (day === today) return "Aujourd'hui";
  if (day === addDays(today, -1)) return "Hier";
  return formatDayLong(day);
}

/** « mars 2026 » : le mois d'arrivée d'une personne (« client depuis mars 2026 »). */
export function monthYear(value: string, timeZone: string): string {
  return new Intl.DateTimeFormat("fr-FR", { timeZone, month: "long", year: "numeric" }).format(
    new Date(value),
  );
}

/** « 10 octobre » : une échéance (jour calendaire) en lettres. */
export function dueDay(day: string): string {
  return formatDayMonth(day);
}

/** Le prénom d'une personne : le premier mot de son nom (« Moussa » pour Moussa Fall). */
export function firstName(name: string): string {
  return name.trim().split(/\s+/)[0] ?? name;
}

/** Initiales d'un nom : « MF » pour Moussa Fall, « G » pour Grossiste. */
export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word.charAt(0).toLocaleUpperCase("fr-FR"))
    .join("");
}
