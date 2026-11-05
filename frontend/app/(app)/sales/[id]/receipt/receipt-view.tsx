"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, MessageCircle, Printer } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { ErrorState } from "@/components/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { useCompanyLocale, useMe } from "@/hooks/use-me";
import { api, unwrap } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { addDecimal, compareDecimal } from "@/lib/decimal";
import {
  formatAmount,
  formatDate,
  formatDateLong,
  formatDateTime,
  formatFigure,
  formatQty,
} from "@/lib/format";
import { labels } from "@/lib/labels";
import { amountInWords } from "@/lib/number-words";
import { displayNumber, qtyWithUnit } from "@/lib/units";
import { cn } from "@/lib/utils";
import { pdfFromResponse } from "@/lib/pdf-share";
import { receiptText, whatsappLink } from "@/lib/whatsapp";

import { PdfActions } from "../../pdf-actions";
import { ReceiptRow, ShopLogo, TicketHeader } from "../../receipt-parts";

type Receipt = Schemas["ReceiptRead"];
type Format = "ticket" | "a4";

const t = labels.receipt;

const BUTTON = cn(
  "inline-flex min-h-bouton items-center justify-center gap-2.5 rounded-bouton px-5 text-[17px] font-bold",
  "outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
);
const SECONDARY = cn(BUTTON, "border-2 border-input bg-card text-foreground hover:bg-voile");

/**
 * Impression : la facture A4 numérote ses pages (« Page 1/2 ») dans la marge basse —
 * Chrome et Edge ; le PDF du serveur le fait partout (bloc T). Le ticket suit la bande.
 */
const A4_PAGE = `@media print { @page { size: A4; margin: 12mm 12mm 16mm;
  @bottom-right { content: "${labels.receipt.page} " counter(page) "/" counter(pages);
  font: 10px sans-serif; } } }`;
const TICKET_PAGE = "@media print { @page { size: 80mm auto; margin: 4mm; } }";

/** Ce qui ne vient pas du reçu : l'échéance de la dette et le moyen du premier paiement. */
type Extras = { dueDate: string | null; method: string | null };

/**
 * Reçu à imprimer, maquette v2 (écrans 05 et 05b) : petit ticket 80 mm en chasse fixe ou
 * facture A4 avec le montant en toutes lettres. Le contenu vient de
 * `GET /sales/{id}/receipt`, figé à la confirmation (ADR 0022) ; la page s'affiche seule,
 * sans barres, et `@page` suit le format choisi. Tampon « VENTE ANNULÉE » si la vente l'est.
 */
export function ReceiptView({ saleId }: { saleId: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const { timeZone } = useCompanyLocale();
  const { data: me } = useMe();
  // Sans choix dans l'adresse, le reçu réglé dans « Ma boutique » (écran 24, ADR 0075).
  const fallback: Format = me?.company.receipt_format ?? "ticket";
  const requested = params.get("format");
  const format: Format = requested === "a4" || requested === "ticket" ? requested : fallback;

  const receipt = useQuery({
    queryKey: queryKeys.sales.receipt(saleId),
    queryFn: () =>
      unwrap(api.GET("/api/v1/sales/{sale_id}/receipt", { params: { path: { sale_id: saleId } } })),
  });
  const sale = useQuery({
    queryKey: queryKeys.sales.detail(saleId),
    queryFn: () =>
      unwrap(api.GET("/api/v1/sales/{sale_id}", { params: { path: { sale_id: saleId } } })),
  });

  const setFormat = (next: Format) =>
    router.replace(next === fallback ? pathname : `${pathname}?format=${next}`, { scroll: false });

  const data = receipt.data;
  const firstPayment = data?.payments.find(
    (payment) => !payment.cancelled && !payment.reversal_of_payment_id,
  );
  const extras: Extras = {
    dueDate: sale.data?.debt?.due_date ?? null,
    method: firstPayment ? labels.paymentMethods[firstPayment.method] : null,
  };
  const text =
    data &&
    receiptText(
      {
        ...data,
        items: data.lines.map((line) => ({ ...line, product_name: line.name })),
      },
      { shop: data.company.name, timeZone, currency: data.company.currency },
    );

  return (
    <div className="mx-auto flex max-w-page flex-col gap-[18px]">
      <style>{format === "a4" ? A4_PAGE : TICKET_PAGE}</style>
      <div className="flex flex-wrap items-center gap-3 print:hidden">
        <Link href={`/sales/${saleId}`} className={SECONDARY}>
          <ArrowLeft className="size-[22px]" aria-hidden />
          {t.back}
        </Link>
        <h1 className="flex-[1_1_240px] text-[28px] leading-[1.45] font-extrabold">
          {data ? t.title(displayNumber(data.sale_no)) : " "}
        </h1>
      </div>

      <div className="flex flex-wrap items-center gap-2.5 rounded-carte border border-border bg-card p-3.5 print:hidden">
        <div role="group" aria-label={t.format} className="flex flex-wrap gap-2">
          {(["ticket", "a4"] as const).map((value) => (
            <button
              key={value}
              type="button"
              aria-pressed={format === value}
              onClick={() => setFormat(value)}
              className={cn(
                "min-h-bouton rounded-champ border-2 px-5 text-[17px] font-bold",
                "outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                format === value
                  ? "border-ventes bg-ventes text-primary-foreground"
                  : "border-input bg-card text-foreground hover:bg-voile",
              )}
            >
              {value === "ticket" ? t.ticket : t.a4}
            </button>
          ))}
        </div>
        <div className="ml-auto flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => window.print()}
            disabled={!data}
            className={cn(BUTTON, "bg-ventes text-primary-foreground hover:bg-ventes/90")}
          >
            <Printer className="size-[22px]" aria-hidden />
            {t.print}
          </button>
          {data && (
            <PdfActions
              load={async () =>
                pdfFromResponse(
                  await api.GET("/api/v1/sales/{sale_id}/receipt/pdf", {
                    params: { path: { sale_id: saleId }, query: { format } },
                    parseAs: "blob",
                  }),
                  `Recu-${displayNumber(data.sale_no)}.pdf`,
                )
              }
              title={t.title(displayNumber(data.sale_no))}
              shareText={text ?? undefined}
              fallback={text ? whatsappLink(text, data.customer?.phone) : undefined}
              className={SECONDARY}
            />
          )}
          {text && (
            <a
              href={whatsappLink(text, data?.customer?.phone)}
              target="_blank"
              rel="noopener noreferrer"
              className={SECONDARY}
            >
              <MessageCircle className="size-[22px]" aria-hidden />
              {t.whatsapp}
            </a>
          )}
        </div>
      </div>

      <div className="flex justify-center overflow-x-auto rounded-carte bg-recu-fond px-4 py-8 print:block print:bg-transparent print:p-0">
        {receipt.isError ? (
          <ErrorState error={receipt.error} onRetry={() => void receipt.refetch()} />
        ) : !data ? (
          <Skeleton className="h-[480px] w-[302px]" />
        ) : format === "ticket" ? (
          <Ticket receipt={data} extras={extras} timeZone={timeZone} />
        ) : (
          <Invoice receipt={data} extras={extras} timeZone={timeZone} />
        )}
      </div>
    </div>
  );
}

function Stamp({ big = false }: { big?: boolean }) {
  return (
    <div
      aria-hidden
      className={cn(
        "absolute left-1/2 -translate-x-1/2 -translate-y-1/2 -rotate-[18deg] border-recu-encre bg-recu-papier/85 tracking-[0.08em] text-recu-encre",
        big
          ? "top-[40%] border-4 px-6 py-2 text-[44px] font-extrabold"
          : "top-[45%] border-3 px-3.5 py-1.5 text-[22px] font-bold",
      )}
    >
      {t.cancelled}
    </div>
  );
}

const positive = (value: string) => compareDecimal(value, "0") === 1;

/** Paiements vivants, additionnés par moyen, dans l'ordre où ils sont venus. */
export function paidByMethod(receipt: Receipt): { method: string; amount: string }[] {
  const totals = new Map<string, string>();
  for (const payment of receipt.payments) {
    if (payment.cancelled || payment.reversal_of_payment_id) continue;
    totals.set(
      payment.method,
      addDecimal(totals.get(payment.method) ?? "0", payment.amount) ?? "0",
    );
  }
  return [...totals].map(([method, amount]) => ({
    method: labels.paymentMethods[method as keyof typeof labels.paymentMethods] ?? method,
    amount,
  }));
}

/** Petit ticket de caisse 80 mm (maquette 05), en JetBrains Mono, noir et blanc. */
function Ticket({
  receipt,
  extras,
  timeZone,
}: {
  receipt: Receipt;
  extras: Extras;
  timeZone: string;
}) {
  const currency = receipt.company.currency;
  // Une vente annulée ne réclame rien : ni reste à payer, ni somme arrêtée.
  const cancelled = receipt.status === "cancelled";
  const owing = positive(receipt.balance) && !cancelled;
  const seller = receipt.seller_name?.trim();
  const dash = <div className="my-2 border-t border-dashed border-recu-encre/70" />;
  const methods = paidByMethod(receipt);
  return (
    <article
      aria-label={t.title(displayNumber(receipt.sale_no))}
      className="relative w-[302px] bg-recu-papier px-4 pt-[18px] pb-6 font-receipt text-[13px] leading-normal text-recu-encre shadow-[0_2px_10px_var(--color-recu-ombre)] print:w-auto print:p-0 print:shadow-none"
    >
      <TicketHeader company={receipt.company} />
      {dash}
      <ReceiptRow
        left={t.saleNo(displayNumber(receipt.sale_no))}
        right={formatDateTime(receipt.confirmed_at ?? receipt.sold_at, timeZone)}
      />
      {receipt.customer && <div>{t.customer(receipt.customer.name)}</div>}
      {seller && <div>{t.seller(seller.split(/\s+/)[0] ?? "")}</div>}
      {dash}
      {receipt.lines.map((line) => (
        <div key={line.product_id} data-testid="ticket-line">
          <div>{line.name}</div>
          <ReceiptRow
            left={`  ${formatQty(line.qty)} x ${formatFigure(line.unit_price, currency)}`}
            right={formatFigure(line.line_total, currency)}
          />
          {positive(line.discount) && (
            <ReceiptRow
              left={`  ${t.lineDiscount}`}
              right={`-${formatFigure(line.discount, currency)}`}
            />
          )}
        </div>
      ))}
      {dash}
      <Totals receipt={receipt} />
      <ReceiptRow
        className="text-base font-bold"
        left={t.total}
        right={formatAmount(receipt.total, currency)}
      />
      {methods.length > 0 ? (
        methods.map((row) => (
          <ReceiptRow
            key={row.method}
            left={t.paidWith(row.method)}
            right={formatAmount(row.amount, currency)}
          />
        ))
      ) : (
        <ReceiptRow
          left={extras.method ? t.paidWith(extras.method) : t.paid}
          right={formatAmount(receipt.paid_total, currency)}
        />
      )}
      {owing && (
        <>
          <ReceiptRow
            className="font-bold"
            left={t.remaining}
            right={formatAmount(receipt.balance, currency)}
          />
          {extras.dueDate && <div>{t.payBefore(formatDate(extras.dueDate))}</div>}
        </>
      )}
      {receipt.returns.length > 0 && (
        <>
          {dash}
          {receipt.returns.map((row) => (
            <ReceiptRow
              key={row.return_no}
              left={t.returnLine(
                displayNumber(row.return_no),
                formatDate(row.returned_at.slice(0, 10)),
              )}
              right={`-${formatFigure(row.total_refund, currency)}`}
            />
          ))}
        </>
      )}
      {dash}
      {receipt.company.receipt_footer && (
        <div className="text-center whitespace-pre-line">{receipt.company.receipt_footer}</div>
      )}
      <div className="mt-2 text-center text-[11px]">{t.madeWith}</div>
      {cancelled && <Stamp />}
    </article>
  );
}

/** Sous-total, remises et TVA, seulement quand ils disent quelque chose. */
function Totals({ receipt, invoice = false }: { receipt: Receipt; invoice?: boolean }) {
  const currency = receipt.company.currency;
  const discounted = positive(receipt.discount_total);
  const taxed = positive(receipt.tax_total);
  if (!discounted && !taxed) return null;
  const row = invoice ? "flex justify-between py-1.5" : "flex justify-between gap-2";
  return (
    <>
      <div className={row}>
        <span>{t.subtotal}</span>
        <span className="numeric">{formatAmount(receipt.subtotal, currency)}</span>
      </div>
      {discounted && (
        <div className={row}>
          <span>{t.discounts}</span>
          <span className="numeric">-{formatAmount(receipt.discount_total, currency)}</span>
        </div>
      )}
      {taxed && (
        <div className={row}>
          <span>{t.vat}</span>
          <span className="numeric">{formatAmount(receipt.tax_total, currency)}</span>
        </div>
      )}
    </>
  );
}

function logoInitials(name: string): string {
  return name
    .trim()
    .split(/\s+/)
    .slice(-2)
    .map((word) => word.charAt(0).toLocaleUpperCase("fr-FR"))
    .join("");
}

/** Dernier morceau de l'adresse, après la dernière virgule : la ville (« Dakar »). */
function cityOf(address: string | null): string | null {
  const city = address?.split(",").at(-1)?.trim();
  return city || null;
}

/**
 * Facture A4 (maquette 05b, refaite au bloc F) : en-tête à logo, client, tableau des lignes
 * (l'en-tête se répète et une ligne ne se coupe jamais d'une page à l'autre), totaux,
 * paiements par moyen, retours liés, montant en lettres, pied de reçu.
 */
function Invoice({
  receipt,
  extras,
  timeZone,
}: {
  receipt: Receipt;
  extras: Extras;
  timeZone: string;
}) {
  const currency = receipt.company.currency;
  // Une vente annulée ne réclame rien : ni reste à payer, ni somme arrêtée.
  const cancelled = receipt.status === "cancelled";
  const owing = positive(receipt.balance) && !cancelled;
  const seller = receipt.seller_name?.trim();
  const ids = t.ids(receipt.company.ninea, receipt.company.rc);
  const withDiscount = receipt.lines.some((line) => positive(line.discount));
  const methods = paidByMethod(receipt);
  const cell = "border-b border-recu-filet px-3 py-2.5 align-top";
  const amount = cn(cell, "numeric text-right whitespace-nowrap");
  const head = cn(
    "border-b-2 border-recu-encre bg-recu-entete px-3 py-2 text-[13px] font-bold tracking-[0.04em] text-recu-gris uppercase",
  );
  return (
    <article
      aria-label={t.title(displayNumber(receipt.sale_no))}
      className="relative box-border w-[794px] max-w-full bg-recu-papier px-14 pt-14 pb-12 text-[15px] leading-normal text-recu-encre shadow-[0_2px_10px_var(--color-recu-ombre)] print:w-auto print:p-0 print:shadow-none"
    >
      <header className="flex flex-wrap justify-between gap-6 border-b-2 border-recu-encre pb-5">
        <div className="flex min-w-0 gap-4">
          <ShopLogo company={receipt.company} className="size-20 shrink-0" />
          {!receipt.company.logo_updated_at && (
            <div
              aria-hidden
              className="flex size-16 shrink-0 items-center justify-center rounded-touche border-2 border-recu-encre text-2xl font-extrabold"
            >
              {logoInitials(receipt.company.name)}
            </div>
          )}
          <div className="min-w-0">
            <div className="text-xl font-extrabold">{receipt.company.name}</div>
            {receipt.company.address && (
              <div className="text-[17px] font-bold">{receipt.company.address}</div>
            )}
            {receipt.company.phone && <div>{t.phone(receipt.company.phone)}</div>}
            {ids && <div className="text-[13px] text-recu-gris">{ids}</div>}
          </div>
        </div>
        <div className="text-right">
          <div className="text-[26px] font-extrabold tracking-[0.04em]">{t.invoice}</div>
          <div className="font-bold">{t.invoiceNo(displayNumber(receipt.sale_no))}</div>
          <div>
            {t.invoiceDate(
              cityOf(receipt.company.address),
              formatDateLong(receipt.confirmed_at ?? receipt.sold_at, timeZone),
            )}
          </div>
          <div className="text-recu-gris">
            {formatDateTime(receipt.confirmed_at ?? receipt.sold_at, timeZone)}
          </div>
          {seller && <div>{t.seller(seller)}</div>}
        </div>
      </header>

      {receipt.customer && (
        <div className="mt-6 mb-5 max-w-80 rounded-[10px] border border-recu-filet px-4 py-3.5">
          <div className="text-[13px] tracking-[0.04em] text-recu-gris uppercase">
            {t.customerTitle}
          </div>
          <div className="text-[17px] font-bold">{receipt.customer.name}</div>
          {receipt.customer.phone && <div>{t.phone(receipt.customer.phone)}</div>}
        </div>
      )}

      <table className="mt-5 w-full border-collapse">
        <thead className="table-header-group">
          <tr>
            <th scope="col" className={cn(head, "text-left")}>
              {t.columns.article}
            </th>
            <th scope="col" className={cn(head, "text-right")}>
              {t.columns.qty}
            </th>
            <th scope="col" className={cn(head, "text-right")}>
              {t.columns.price}
            </th>
            {withDiscount && (
              <th scope="col" className={cn(head, "text-right")}>
                {t.columns.discount}
              </th>
            )}
            <th scope="col" className={cn(head, "text-right")}>
              {t.columns.amount}
            </th>
          </tr>
        </thead>
        <tbody>
          {receipt.lines.map((line) => (
            <tr key={line.product_id} className="break-inside-avoid" data-testid="invoice-line">
              <td className={cell}>
                <div className="font-bold">{line.name}</div>
                {line.description && (
                  <div className="text-[13px] whitespace-pre-line text-recu-gris">
                    {line.description}
                  </div>
                )}
              </td>
              <td className={amount}>{qtyWithUnit(line.qty, line.unit)}</td>
              <td className={amount}>{formatAmount(line.unit_price, currency)}</td>
              {withDiscount && (
                <td className={amount}>
                  {positive(line.discount) ? `-${formatAmount(line.discount, currency)}` : ""}
                </td>
              )}
              <td className={amount}>{formatAmount(line.line_total, currency)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="mt-4 flex break-inside-avoid justify-end">
        <div className="w-[320px]">
          <Totals receipt={receipt} invoice />
          <div className="flex justify-between border-y-2 border-recu-encre py-2 text-lg font-extrabold">
            <span>{t.invoiceTotal}</span>
            <span className="numeric">{formatAmount(receipt.total, currency)}</span>
          </div>
          {methods.map((row) => (
            <div key={row.method} className="flex justify-between py-1.5">
              <span>{t.paidWith(row.method)}</span>
              <span className="numeric">{formatAmount(row.amount, currency)}</span>
            </div>
          ))}
          <div className="flex justify-between py-1.5">
            <span>{t.alreadyPaid}</span>
            <span className="numeric">{formatAmount(receipt.paid_total, currency)}</span>
          </div>
          {owing && (
            <div className="flex justify-between py-1.5 font-bold">
              <span>{t.invoiceRemaining}</span>
              <span className="numeric">{formatAmount(receipt.balance, currency)}</span>
            </div>
          )}
        </div>
      </div>

      {receipt.returns.length > 0 && (
        <section className="mt-6 break-inside-avoid">
          <h2 className="text-[13px] font-bold tracking-[0.04em] text-recu-gris uppercase">
            {t.returnsTitle}
          </h2>
          {receipt.returns.map((row) => (
            <div
              key={row.return_no}
              className="flex justify-between border-b border-recu-filet py-1.5"
            >
              <span>
                {t.returnLine(
                  displayNumber(row.return_no),
                  formatDateLong(row.returned_at, timeZone),
                )}
              </span>
              <span className="numeric">-{formatAmount(row.total_refund, currency)}</span>
            </div>
          ))}
        </section>
      )}

      {!cancelled && (
        <p className="mt-6 break-inside-avoid">
          {t.inWords}
          <strong>{amountInWords(receipt.total)}</strong>.
        </p>
      )}
      <p className={cn(cancelled ? "mt-6" : "mt-1.5", "text-recu-gris")}>
        {positive(receipt.tax_total)
          ? t.vatIncluded(formatAmount(receipt.tax_total, currency))
          : t.noVat}
        {owing && extras.dueDate && ` ${t.remainingBefore(formatDateLong(extras.dueDate))}`}
      </p>

      <footer className="mt-12 flex break-inside-avoid flex-wrap justify-between gap-6">
        <div className="text-recu-gris">
          {receipt.company.receipt_footer ? (
            <div className="whitespace-pre-line">{receipt.company.receipt_footer}</div>
          ) : (
            t.thanks
          )}
          <div className="mt-2.5 flex items-center gap-1.5 text-xs text-recu-gris">
            {t.invoiceMadeWith}
            <Image
              src="/brand/coges-wordmark.png"
              alt="CoGes"
              width={51}
              height={12}
              unoptimized
              style={{ width: 51, height: 12 }}
            />
          </div>
        </div>
        <div className="min-w-[200px] text-center text-recu-gris">
          {t.signature}
          <div className="h-16" />
        </div>
      </footer>
      {cancelled && <Stamp big />}
    </article>
  );
}
