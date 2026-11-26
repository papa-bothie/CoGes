import offres from "@/content/offres.json";

/** Durée de l'essai, fixée en base (trigger `companies_start_trial`, ADR 0091 puis 0132),
 * lue dans la source partagée des offres. */
export const TRIAL_DAYS: number = offres.trialDays;
