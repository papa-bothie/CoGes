import type { SignupBucket } from "@/lib/api/schema";

export type RevenuePeriod = "current_month" | "previous_month" | "custom";
export type Granularity = "month" | "week";

export const REVENUE_PERIODS: { value: RevenuePeriod; label: string }[] = [
  { value: "current_month", label: "Mois en cours" },
  { value: "previous_month", label: "Mois précédent" },
  { value: "custom", label: "Personnalisée" },
];

export const GRANULARITIES: { value: Granularity; label: string }[] = [
  { value: "month", label: "Par mois" },
  { value: "week", label: "Par semaine" },
];

const MONTHS = [
  "janv.",
  "févr.",
  "mars",
  "avr.",
  "mai",
  "juin",
  "juil.",
  "août",
  "sept.",
  "oct.",
  "nov.",
  "déc.",
];

/**
 * Un jour de calendrier (`2026-10-01`) en `01/10/2026`, sans passer par `Date` : un jour
 * n'a pas de fuseau, et l'heure du navigateur ne doit pas le décaler d'un jour.
 */
export function formatDay(day: string): string {
  const [year, month, date] = day.split("-");
  return `${date}/${month}/${year}`;
}

/** « du 01/10/2026 au 24/10/2026 », ou « le 24/10/2026 » pour un seul jour. */
export function formatSpan(start: string, end: string): string {
  return start === end ? `le ${formatDay(start)}` : `du ${formatDay(start)} au ${formatDay(end)}`;
}

/** Libellé court d'une période : « oct. 2026 » ou « 19/10 » (semaine du lundi 19/10). */
export function bucketLabel(bucket: SignupBucket, granularity: Granularity): string {
  const [year, month, date] = bucket.start.split("-");
  if (granularity === "month") return `${MONTHS[Number(month) - 1]} ${year}`;
  return `${date}/${month}`;
}

/** Libellé complet, pour le tableau et les lecteurs d'écran. */
export function bucketTitle(bucket: SignupBucket, granularity: Granularity): string {
  if (granularity === "month") {
    const [year, month] = bucket.start.split("-");
    return `${MONTHS[Number(month) - 1]} ${year}`;
  }
  return `Semaine ${formatSpan(bucket.start, bucket.end)}`;
}

/** Hauteur d'une barre en pourcentage de la plus haute ; une barre non nulle reste visible. */
export function barHeight(count: number, max: number): number {
  if (count <= 0 || max <= 0) return 0;
  return Math.max(4, Math.round((count / max) * 100));
}
