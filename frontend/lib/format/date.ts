/**
 * Dates affichées `jj/mm/aaaa`, heures sur 24 h, **dans le fuseau de l'entreprise**
 * (`me.company.timezone`), pas dans celui du navigateur : une caisse de Dakar consultée
 * depuis Paris doit montrer les mêmes journées.
 */

const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/;

const formatters = new Map<string, Intl.DateTimeFormat>();

function formatter(timeZone: string, withTime: boolean): Intl.DateTimeFormat {
  const key = `${timeZone}|${withTime}`;
  let cached = formatters.get(key);
  if (!cached) {
    cached = new Intl.DateTimeFormat("fr-FR", {
      timeZone,
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      ...(withTime ? { hour: "2-digit", minute: "2-digit", hourCycle: "h23" } : {}),
    });
    formatters.set(key, cached);
  }
  return cached;
}

/**
 * `formatDate("2026-09-29T23:30:00Z", "Africa/Dakar")` → « 29/09/2026 ».
 * Une date seule (« 2026-09-29 », sans heure) n'est jamais décalée de fuseau.
 */
export function formatDate(value: string | null | undefined, timeZone = "UTC"): string {
  if (!value) return "—";
  const dateOnly = DATE_ONLY.exec(value);
  if (dateOnly) return `${dateOnly[3]}/${dateOnly[2]}/${dateOnly[1]}`;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return formatter(timeZone, false).format(date);
}

/** « 29/09/2026 14:05 ». */
export function formatDateTime(value: string | null | undefined, timeZone = "UTC"): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return formatter(timeZone, true).format(date).replace(",", "");
}

function parts(value: string, timeZone: string, options: Intl.DateTimeFormatOptions) {
  return new Intl.DateTimeFormat("fr-FR", { timeZone, ...options }).formatToParts(new Date(value));
}

/** Heure de la maquette v2 : « 10 h 42 », « 9 h 58 », dans le fuseau de l'entreprise. */
export function formatClock(value: string | null | undefined, timeZone = "UTC"): string {
  if (!value || Number.isNaN(new Date(value).getTime())) return "—";
  const found = parts(value, timeZone, { hour: "numeric", minute: "2-digit", hourCycle: "h23" });
  const hour = found.find((part) => part.type === "hour")?.value ?? "";
  const minute = found.find((part) => part.type === "minute")?.value ?? "";
  return `${Number(hour)} h ${minute}`;
}

const capitalise = (text: string) => text.charAt(0).toLocaleUpperCase("fr-FR") + text.slice(1);

/** Jour calendaire (« 2026-10-06 ») en toutes lettres : « Mardi 6 octobre ». */
export function formatDayLong(day: string): string {
  const match = DATE_ONLY.exec(day);
  if (!match) return "—";
  const text = new Intl.DateTimeFormat("fr-FR", {
    timeZone: "UTC",
    weekday: "long",
    day: "numeric",
    month: "long",
  }).format(new Date(`${day}T12:00:00Z`));
  return capitalise(text);
}

/** Jour de la semaine abrégé sous une barre de graphique : « Mer », « Jeu ». */
export function formatWeekdayShort(day: string): string {
  if (!DATE_ONLY.test(day)) return "—";
  const text = new Intl.DateTimeFormat("fr-FR", { timeZone: "UTC", weekday: "short" }).format(
    new Date(`${day}T12:00:00Z`),
  );
  return capitalise(text.replace(".", ""));
}

/** Jour et mois en lettres : « 20 octobre » (échéance d'une dette, maquette 04). */
export function formatDayMonth(value: string | null | undefined, timeZone = "UTC"): string {
  if (!value) return "—";
  const day = DATE_ONLY.test(value) ? `${value}T12:00:00Z` : value;
  const date = new Date(day);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("fr-FR", {
    timeZone: DATE_ONLY.test(value) ? "UTC" : timeZone,
    day: "numeric",
    month: "long",
  }).format(date);
}
