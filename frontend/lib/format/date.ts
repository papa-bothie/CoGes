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
