/**
 * Durées payées d'un abonnement (ADR 0132, 0134) : 1 mois, 6 mois sans remise, 1 an à -10 %.
 *
 * `nextPeriodEnd` montre à l'administrateur, avant de valider, la fin que le serveur
 * posera : même départ que `_period_start` (ADR 0133) et même calcul de fin de mois que
 * `_add_months` (`backend/app/modules/platform/service.py`). Le serveur reste l'autorité :
 * la date affichée après l'enregistrement est celle qu'il renvoie.
 */

export type Months = 1 | 6 | 12;

export const PERIODS: readonly Months[] = [1, 6, 12];

export const PERIOD_LABELS: Record<Months, string> = {
  1: "1 mois",
  6: "6 mois",
  12: "1 an",
};

/** Jours de grâce après la fin d'une période payée (`renewal.GRACE_DAYS`). */
const GRACE_DAYS = 3;
const DAY_MS = 86_400_000;

/** Même jour `months` mois plus tard, ramené au dernier jour s'il n'existe pas (UTC). */
export function addMonths(moment: Date, months: number): Date {
  const index = moment.getUTCMonth() + months;
  const year = moment.getUTCFullYear() + Math.floor(index / 12);
  const month = index % 12;
  const lastDay = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
  const result = new Date(moment.getTime());
  result.setUTCFullYear(year, month, Math.min(moment.getUTCDate(), lastDay));
  return result;
}

/** La fin de période après un paiement de `months` mois enregistré maintenant. */
export function nextPeriodEnd(
  subscription: { status: string; current_period_end: string | null | undefined },
  months: number,
  now: Date = new Date(),
): Date {
  const ends = subscription.current_period_end ? new Date(subscription.current_period_end) : null;
  const renewing =
    ends !== null &&
    subscription.status !== "suspended" &&
    ends.getTime() >= now.getTime() - GRACE_DAYS * DAY_MS;
  return addMonths(renewing ? ends : now, months);
}
