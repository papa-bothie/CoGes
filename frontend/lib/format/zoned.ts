/**
 * Bornes d'une journée **dans le fuseau de l'entreprise**, en instant ISO pour l'API.
 * Un filtre « du 01/09 au 30/09 » doit couvrir les mêmes ventes à Dakar et à Paris.
 */

function offsetMs(instant: number, timeZone: string): number {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).formatToParts(new Date(instant));
  const get = (type: string) => Number(parts.find((part) => part.type === type)?.value);
  const asUtc = Date.UTC(
    get("year"),
    get("month") - 1,
    get("day"),
    get("hour"),
    get("minute"),
    get("second"),
  );
  return asUtc - Math.floor(instant / 1000) * 1000;
}

function startOfDay(day: string, timeZone: string): number | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day);
  if (!match) return null;
  const guess = Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  // Deux passes : l'offset du jour peut différer de celui de minuit UTC (heure d'été).
  const first = guess - offsetMs(guess, timeZone);
  return guess - offsetMs(first, timeZone);
}

/** « 2026-09-01 » → premier instant de la journée dans `timeZone`. */
export function dayStartIso(day: string, timeZone: string): string | null {
  const start = startOfDay(day, timeZone);
  return start === null ? null : new Date(start).toISOString();
}

/** « 2026-09-30 » → dernier instant (à la milliseconde) de la journée dans `timeZone`. */
export function dayEndIso(day: string, timeZone: string): string | null {
  const start = startOfDay(day, timeZone);
  if (start === null) return null;
  const next = new Date(start + 36 * 3600_000).toISOString().slice(0, 10);
  const nextStart = startOfDay(next, timeZone);
  return nextStart === null ? null : new Date(nextStart - 1).toISOString();
}

/** « 2026-09-30T10:15 » (champ `datetime-local`) lu dans `timeZone` → instant ISO. */
export function zonedDateTimeIso(value: string, timeZone: string): string | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(value);
  if (!match) return null;
  const [, y, m, d, h, mi] = match.map(Number);
  const guess = Date.UTC(y!, m! - 1, d!, h!, mi!);
  const first = guess - offsetMs(guess, timeZone);
  return new Date(guess - offsetMs(first, timeZone)).toISOString();
}
