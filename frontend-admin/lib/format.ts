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

/** Temps restant avant une échéance : « reste 1 h 52 », « reste 8 min », « terminé ». */
export function formatRemaining(until: string, now: number = Date.now()): string {
  const minutes = Math.ceil((Date.parse(until) - now) / 60_000);
  if (minutes <= 0) return "terminé";
  if (minutes < 60) return `reste ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return `reste ${hours} h${rest ? ` ${String(rest).padStart(2, "0")}` : ""}`;
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

export const PLATFORM_ROLE_LABELS: Record<string, string> = {
  administrator: "Administrateur",
  support: "Support",
};

export const MERCHANT_STATUS_LABELS: Record<string, string> = {
  active: "Actif",
  deactivated: "Désactivé",
  company_suspended: "Entreprise suspendue",
};

/**
 * Ancienneté en mots : « à l'instant », « il y a 5 min », « il y a 3 h », « hier »,
 * « il y a 4 jours », « il y a 2 mois ». La date exacte reste en infobulle.
 */
export function formatRelative(value: string | null | undefined, now: number = Date.now()): string {
  if (!value) return "Jamais";
  const seconds = Math.max(0, (now - Date.parse(value)) / 1000);
  if (seconds < 60) return "à l'instant";
  if (seconds < 3600) return `il y a ${Math.floor(seconds / 60)} min`;
  if (seconds < 86_400) return `il y a ${Math.floor(seconds / 3600)} h`;
  const days = Math.floor(seconds / 86_400);
  if (days === 1) return "hier";
  if (days < 31) return `il y a ${days} jours`;
  const months = Math.floor(days / 30.5);
  if (months < 12) return `il y a ${months} mois`;
  const years = Math.floor(days / 365);
  return `il y a ${years} an${years > 1 ? "s" : ""}`;
}

/** « Aïssatou Diop » → « Aïssatou D. » ; un nom d'un seul mot reste entier. */
export function shortName(name: string | null | undefined): string {
  if (!name) return "Quelqu'un";
  const parts = name.trim().split(/\s+/);
  if (parts.length < 2) return parts[0] ?? name;
  const last = parts[parts.length - 1] ?? "";
  return `${parts.slice(0, -1).join(" ")} ${last.charAt(0).toUpperCase()}.`;
}
