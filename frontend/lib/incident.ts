/**
 * Référence d'incident lisible au téléphone (ADR 0085) : les 8 premiers signes de
 * l'identifiant de requête, en majuscules, par deux groupes de quatre (« AB12 CD34 »).
 * Les journaux et Sentry gardent l'identifiant complet ; ce début suffit à le retrouver.
 */
export function incidentReference(requestId: string | null | undefined): string | null {
  if (!requestId) return null;
  const compact = requestId.replace(/[^A-Za-z0-9]/g, "").toUpperCase();
  if (compact.length < 8) return null;
  return `${compact.slice(0, 4)} ${compact.slice(4, 8)}`;
}
