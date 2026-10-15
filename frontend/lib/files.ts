/**
 * Fichiers Excel, maquette v2 (écran 24e, ADR 0075) : les périodes d'un export de ventes,
 * le nom d'un fichier préparé, et l'enregistrement d'un fichier reçu de l'API.
 */
import { addDays } from "@/lib/period";

export type SalesPeriod = "month" | "last" | "year";

/** Bornes incluses d'une période, en jours de l'entreprise (« 2026-10-06 »). */
export function salesPeriod(period: SalesPeriod, today: string): { from: string; to: string } {
  const [year, month] = today.split("-");
  if (period === "year") return { from: `${year}-01-01`, to: today };
  const first = `${year}-${month}-01`;
  if (period === "month") return { from: first, to: today };
  const end = addDays(first, -1);
  return { from: `${end.slice(0, 7)}-01`, to: end };
}

const MONTH = new Intl.DateTimeFormat("fr-FR", { timeZone: "UTC", month: "long", year: "numeric" });
const SHORT = new Intl.DateTimeFormat("fr-FR", {
  timeZone: "UTC",
  day: "2-digit",
  month: "2-digit",
});
const at = (day: string) => new Date(`${day}T12:00:00Z`);

/**
 * Ce que couvre un export : « septembre 2026 » pour un mois (entier ou en cours), « 2026 »
 * pour une année depuis le 1er janvier, sinon « 01/09 au 15/09 ».
 */
export function periodName(from: string, to: string): string {
  if (from.endsWith("-01") && from.slice(0, 7) === to.slice(0, 7)) return MONTH.format(at(from));
  if (from.endsWith("-01-01") && from.slice(0, 4) === to.slice(0, 4)) return from.slice(0, 4);
  return `${SHORT.format(at(from))} au ${SHORT.format(at(to))}`;
}

/** « attachment; filename="ventes.xlsx" » → « ventes.xlsx ». */
export function attachmentName(header: string | null, fallback: string): string {
  const match = header ? /filename="?([^";]+)"?/.exec(header) : null;
  return match?.[1] ?? fallback;
}

/** Enregistre un fichier reçu de l'API, comme un lien de téléchargement. */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
