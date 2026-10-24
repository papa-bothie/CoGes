/** Affichage des dates : `jj/mm/aaaa`, heures sur 24 h, fuseau de Dakar (CLAUDE.md § 5). */
const DATE = new Intl.DateTimeFormat("fr-FR", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  timeZone: "Africa/Dakar",
});
const DATE_TIME = new Intl.DateTimeFormat("fr-FR", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
  timeZone: "Africa/Dakar",
});

const TIME = new Intl.DateTimeFormat("fr-FR", {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
  timeZone: "Africa/Dakar",
});

/** Heure seule, à la seconde : « vérifié à 10:45:07 ». */
export function formatTime(value: string): string {
  return TIME.format(new Date(value));
}

/** Âge d'un battement ou d'un retard : « 12 s », « 4 min », « 3 h », « 2 j ». */
export function formatAge(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 60) return `${Math.round(seconds)} s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h`;
  return `${Math.floor(seconds / 86400)} j`;
}

const FCFA = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 });

/** Montant en francs CFA : « 14 900 FCFA », espaces fines insécables, sans décimales. */
export function formatFcfa(value: string | null | undefined): string {
  if (value === null || value === undefined) return "Sur devis";
  return `${FCFA.format(Number(value)).replace(/\s/g, "\u202f")}\u202fFCFA`;
}

export function formatDate(value: string | null | undefined): string {
  return value ? DATE.format(new Date(value)) : "—";
}

export function formatDateTime(value: string | null | undefined): string {
  return value ? DATE_TIME.format(new Date(value)).replace(" ", " à ") : "Jamais";
}

export const STATUS_LABELS: Record<string, string> = {
  trial: "Essai",
  active: "Active",
  suspended: "Suspendue",
};

export const ROLE_LABELS: Record<string, string> = {
  gerant: "Gérant",
  vendeur: "Vendeur",
  comptable: "Comptable",
};

export const SUBSCRIPTION_LABELS: Record<string, string> = {
  trial: "Essai",
  active: "Actif",
  past_due: "En retard",
  suspended: "Suspendu",
};

export const PAYMENT_METHOD_LABELS: Record<string, string> = {
  wave: "Wave",
  orange_money: "Orange Money",
  cash: "Espèces",
  bank_transfer: "Virement",
};
