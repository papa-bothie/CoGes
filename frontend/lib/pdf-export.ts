/**
 * Exports PDF pour le comptable (prompt 35, bloc X, ADR 0114) : la période choisie à
 * l'écran, en jours de l'entreprise, et les deux façons d'obtenir le document.
 *
 * - **immédiat** (état du stock, dépenses, dettes) : le PDF arrive dans la réponse ;
 *   au-delà de 1 000 lignes, le serveur répond `report_too_large` et l'écran propose de
 *   le préparer par la file ;
 * - **en tâche de fond** (ventes, journal de caisse, potentiellement longs) : la demande est
 *   enregistrée, le fichier arrive dans Réglages → Fichiers comme l'export Excel.
 */
import { addDays } from "@/lib/period";

export type PdfKind = "sales" | "cash" | "stock" | "expenses" | "debts";
export type PdfPeriodChoice = "day" | "week" | "month" | "custom";

/** 366 jours au plus, comme le serveur (`MAX_PERIOD_DAYS`). */
export const MAX_PDF_DAYS = 366;

/** Les documents longs, produits par le worker. */
export const QUEUED_PDFS: readonly PdfKind[] = ["sales", "cash"];
/** Réponse d'un document immédiat trop long : il passe alors par la file. */
export const TOO_LARGE = "report_too_large";
/** Les documents datés « à aujourd'hui », sans période à choisir. */
export const UNDATED_PDFS: readonly PdfKind[] = ["stock", "debts"];

export type PdfPeriod = { from: string; to: string };

function daysBetween(from: string, to: string): number {
  return (Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 86_400_000;
}

/**
 * La période d'un choix : aujourd'hui, cette semaine (depuis lundi), ce mois (depuis le
 * 1er), ou des dates choisies. `null` si les dates choisies sont absentes, inversées ou
 * trop éloignées.
 */
export function pdfPeriod(
  choice: PdfPeriodChoice,
  today: string,
  custom: { from: string; to: string } = { from: "", to: "" },
): PdfPeriod | null {
  if (choice === "day") return { from: today, to: today };
  if (choice === "month") return { from: `${today.slice(0, 8)}01`, to: today };
  if (choice === "week") {
    const weekday = new Date(`${today}T00:00:00Z`).getUTCDay(); // 0 = dimanche
    return { from: addDays(today, -((weekday + 6) % 7)), to: today };
  }
  const { from, to } = custom;
  if (!from || !to || from > to) return null;
  if (daysBetween(from, to) + 1 > MAX_PDF_DAYS) return null;
  return { from, to };
}
