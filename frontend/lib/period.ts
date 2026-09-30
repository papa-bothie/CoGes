/**
 * Période d'analyse commune aux écrans de pilotage, gardée **dans l'URL** (`?period=30d`,
 * ou `?period=custom&from=…&to=…`). Les bornes sont des jours calendaires **dans le fuseau
 * de l'entreprise** : « aujourd'hui » à Dakar n'est pas « aujourd'hui » à Paris à 23 h 30.
 *
 * Aucun montant ici : seulement des dates. Les chiffres de la période viennent de l'API.
 */

export const PERIOD_PRESETS = ["7d", "30d", "90d", "month", "custom"] as const;
export type PeriodPreset = (typeof PERIOD_PRESETS)[number];

export const DEFAULT_PRESET: PeriodPreset = "30d";

export type Period = { preset: PeriodPreset; from: string; to: string };

const DAY = /^\d{4}-\d{2}-\d{2}$/;

/** Jour courant (« 2026-09-30 ») dans `timeZone`. */
export function todayIn(timeZone: string, now: Date = new Date()): string {
  // `en-CA` rend le format ISO « AAAA-MM-JJ ».
  return new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(now);
}

/** Décale un jour calendaire (arithmétique de dates, pas d'heure ni de fuseau). */
export function addDays(day: string, delta: number): string {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(Date.UTC(y!, m! - 1, d! + delta)).toISOString().slice(0, 10);
}

function isPreset(value: string | null): value is PeriodPreset {
  return value !== null && (PERIOD_PRESETS as readonly string[]).includes(value);
}

/**
 * Lit la période depuis l'URL. Une période personnalisée incomplète, inversée ou mal
 * formée retombe sur le préréglage par défaut plutôt que d'envoyer une borne absurde.
 */
export function resolvePeriod(
  params: { period: string | null; from: string | null; to: string | null },
  timeZone: string,
  now: Date = new Date(),
): Period {
  const today = todayIn(timeZone, now);
  const preset = isPreset(params.period) ? params.period : DEFAULT_PRESET;
  switch (preset) {
    case "7d":
      return { preset, from: addDays(today, -6), to: today };
    case "90d":
      return { preset, from: addDays(today, -89), to: today };
    case "month":
      return { preset, from: `${today.slice(0, 8)}01`, to: today };
    case "custom": {
      const { from, to } = params;
      if (from && to && DAY.test(from) && DAY.test(to) && from <= to) {
        return { preset, from, to };
      }
      return resolvePeriod({ period: DEFAULT_PRESET, from: null, to: null }, timeZone, now);
    }
    default:
      return { preset: "30d", from: addDays(today, -29), to: today };
  }
}
