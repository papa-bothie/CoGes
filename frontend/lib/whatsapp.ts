import { compareDecimal } from "@/lib/decimal";
import { formatAmount, formatDateTime, formatQty } from "@/lib/format";
import { labels } from "@/lib/labels";
import { phoneDigits } from "@/lib/phone";
import { displayNumber } from "@/lib/units";

type ReceiptSale = {
  sale_no: string;
  sold_at: string;
  total: string;
  paid_total: string;
  balance: string;
  items: readonly {
    product_name: string | null;
    qty: string;
    unit_price: string;
    line_total: string;
  }[];
};

/**
 * Le reçu en texte, pour WhatsApp (maquette v2, écrans 02d, 04 et 05) : nom de la boutique,
 * numéro et date, une ligne par article, total, payé et reste. Aucune API payante : le texte
 * part dans un lien `wa.me` que le téléphone ouvre.
 */
export function receiptText(
  sale: ReceiptSale,
  { shop, timeZone, currency = "XOF" }: { shop: string; timeZone: string; currency?: string },
): string {
  const t = labels.whatsapp;
  const money = (value: string) => formatAmount(value, currency).replace(/ /g, " ");
  const lines = [
    shop,
    t.saleLine(displayNumber(sale.sale_no), formatDateTime(sale.sold_at, timeZone)),
    ...sale.items.map((item) =>
      t.itemLine(
        item.product_name ?? labels.sales.deletedProduct,
        formatQty(item.qty),
        money(item.unit_price),
        money(item.line_total),
      ),
    ),
    t.total(money(sale.total)),
    t.paid(money(sale.paid_total)),
  ];
  if (compareDecimal(sale.balance, "0") === 1) lines.push(t.remaining(money(sale.balance)));
  return lines.join("\n");
}

/** Lien `wa.me` : vers le client si son numéro est complet (+221), sinon au choix. */
export function whatsappLink(text: string, phone: string | null | undefined): string {
  const digits = phone ? phoneDigits(phone) : "";
  const target = digits.length === 9 ? `221${digits}` : "";
  return `https://wa.me/${target}?text=${encodeURIComponent(text)}`;
}
