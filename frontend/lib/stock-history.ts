import type { Schemas } from "@/lib/api/schema";
import { formatClock, formatDayLong } from "@/lib/format";
import { labels } from "@/lib/labels";
import { addDays, todayIn } from "@/lib/period";
import { qtyWithUnit } from "@/lib/units";

type Item = Schemas["ProductHistoryItem"];

/** Teinte de la pastille : vente (sortie), perte, entrée, correction. */
export type HistoryKind = "out" | "loss" | "in" | "fix";

const t = labels.stockScreens.sheet.history;

/** « Vendu à Awa Diop », « Livraison de Grossiste Sandaga », « Abîmé »… (maquette 08). */
export function historyPhrase(item: Item): string {
  if (item.is_reversal) {
    return item.type === "customer_return_in" ? t.saleCancelled : t.reversed;
  }
  const who = item.counterparty;
  switch (item.type) {
    case "sale_out":
      return who ? t.soldTo(who) : t.sold;
    case "customer_return_in":
      return who ? t.returnedBy(who) : t.returned;
    case "purchase_in":
      return who ? t.deliveryFrom(who) : t.delivery;
    case "supplier_return_out":
      return who ? t.sentBackTo(who) : t.sentBack;
    case "initial":
      return t.initial;
    case "loss":
      return item.reason_code ? t.loss[item.reason_code as keyof typeof t.loss] : t.lossUnknown;
    case "adjustment":
      if (item.reason_code === "found") return labels.stock.reasons.found;
      if (item.reason_code === "supplier_gift") return labels.stock.reasons.supplier_gift;
      return item.reason_code === "count_error" ? t.countError : t.correction;
  }
}

export function historyKind(item: Item): HistoryKind {
  if (item.type === "adjustment" || item.is_reversal) return "fix";
  if (item.type === "loss") return "loss";
  return Number(item.qty_delta) < 0 ? "out" : "in";
}

/** « Aujourd'hui, 10 h 42 », « Hier, 18 h 20 », puis « Samedi 3 octobre ». */
export function historyWhen(value: string, timeZone: string, now: Date = new Date()): string {
  const today = todayIn(timeZone, now);
  const day = todayIn(timeZone, new Date(value));
  const time = formatClock(value, timeZone);
  if (day === today) return t.today(time);
  if (day === addDays(today, -1)) return t.yesterday(time);
  return formatDayLong(day);
}

/** « −1 sac », « +10 sacs » : signe, quantité et unité accordée. */
export function historyQty(item: Item, unit: string): string {
  const negative = item.qty_delta.startsWith("-");
  const magnitude = negative ? item.qty_delta.slice(1) : item.qty_delta;
  return `${negative ? "−" : "+"}${qtyWithUnit(magnitude, unit)}`;
}
