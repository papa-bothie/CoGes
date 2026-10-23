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
