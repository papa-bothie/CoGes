/**
 * Les mots et les chiffres de L'argent (maquette v2, écrans 17 à 21) : signe des montants,
 * libellé des barres, phrase d'une ligne de caisse. Les montants restent des chaînes de
 * l'API : aucun flottant sur de l'argent.
 */
import type { Schemas } from "@/lib/api/schema";
import { formatAmount, formatClock, formatDayMonth, formatWeekdayShort } from "@/lib/format";
import { labels } from "@/lib/labels";
import { addDays } from "@/lib/period";

const t = labels.moneyScreens;
/** Le vrai signe moins (U+2212), comme la maquette : « −35 000 F ». */
export const MINUS = "−";

/** Vrai si le montant de l'API est négatif (« -1300.00 »). */
export function isNegative(value: string): boolean {
  return value.trim().startsWith("-");
}

/** Montant sans signe (« -1300.00 » → « 1300.00 »). */
export function absolute(value: string): string {
  return value.trim().replace(/^[-+]/, "");
}

/** « +275 000 F », « −16 000 F », « 0 F ». */
export function signedAmount(value: string, currency: string): string {
  const text = formatAmount(absolute(value), currency);
  if (/^0+(\.0+)?$/.test(absolute(value))) return text;
  return `${isNegative(value) ? MINUS : "+"}${text}`;
}

/** Comme `signedAmount`, sans « + » : le net par moyen de la maquette 21 (« 12 500 F »). */
export function netAmount(value: string, currency: string): string {
  const text = formatAmount(absolute(value), currency);
  return isNegative(value) && !/^0+(\.0+)?$/.test(absolute(value)) ? `${MINUS}${text}` : text;
}

type Bucket = Schemas["MoneyBucket"];

/** Le mot sous une paire de barres : « Matin », « Mer », « Semaine 2 ». */
export function bucketLabel(bucket: Bucket, grain: Schemas["MoneyOverview"]["grain"]): string {
  if (grain === "moment") return t.moments[bucket.key as keyof typeof t.moments] ?? bucket.key;
  if (grain === "day") return formatWeekdayShort(bucket.start);
  return t.week(Number(bucket.key.replace("week-", "")) || 1);
}

/** « payée aujourd'hui », « hier », « le 3 octobre » : le jour de la plus grosse dépense. */
export function paidDay(day: string, today: string): string {
  if (day === today) return t.paidToday;
  if (day === addDays(today, -1)) return t.paidYesterday;
  return t.paidOn(formatDayMonth(day));
}

/** Jours d'ici l'échéance (négatif si elle est passée). */
export function daysUntil(day: string, today: string): number {
  return Math.round(
    (Date.parse(`${day}T12:00:00Z`) - Date.parse(`${today}T12:00:00Z`)) / 86_400_000,
  );
}

/** Une échéance est proche à 7 jours ou moins (maquette 19 : en orange). */
export const DUE_SOON_DAYS = 7;

type Line = Schemas["CashJournalLine"];

/** « 1046 » pour « V-001046 » : le numéro de la maquette, sans préfixe ni zéros. */
export function shortNumber(documentNo: string | null): string {
  if (!documentNo) return "";
  const digits = documentNo.replace(/^\D+-?/, "").replace(/^0+(?=\d)/, "");
  return digits || documentNo;
}

/** Ce que dit une ligne de caisse : « Vente n° 1046 · Awa Diop », « Dépense · Électricité ». */
export function cashLineTitle(line: Line): string {
  const who = line.party_name ?? t.cash.walkIn;
  switch (line.kind) {
    case "sale":
      return t.cash.sale(shortNumber(line.document_no), who);
    case "debt_in":
      return t.cash.debtIn(line.party_name ?? t.cash.walkIn);
    case "debt_out":
      return t.cash.debtOut(line.party_name ?? "");
    case "expense":
      return t.cash.expense(line.party_name ?? line.expense_label ?? "");
    case "refund":
      return t.cash.refund(shortNumber(line.document_no), who);
    case "other_in":
      return t.cash.otherIn;
    default:
      return t.cash.otherOut;
  }
}

/** Titre d'une ligne, annulation comprise : « Annulation : Vente n° 1046 · Awa Diop (…) ». */
export function cashLineText(line: Line): string {
  const title = cashLineTitle(line);
  return line.is_reversal ? t.cash.reversal(title, line.cancel_reason ?? "") : title;
}

/** « 10 h 42 · Wave ». */
export function cashLineDetail(line: Line, timeZone: string): string {
  const method =
    labels.paymentMethods[line.method as keyof typeof labels.paymentMethods] ?? line.method;
  return t.cash.line(formatClock(line.paid_at, timeZone), method);
}
