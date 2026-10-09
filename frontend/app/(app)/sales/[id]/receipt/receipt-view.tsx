"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, MessageCircle, Printer } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import type { ReactNode } from "react";

import { ErrorState } from "@/components/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { useCompanyLocale } from "@/hooks/use-me";
import { api, unwrap } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { compareDecimal } from "@/lib/decimal";
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
import { displayNumber } from "@/lib/units";
import { cn } from "@/lib/utils";
import { receiptText, whatsappLink } from "@/lib/whatsapp";

type Receipt = Schemas["ReceiptRead"];
type Format = "ticket" | "a4";

const t = labels.receipt;

const BUTTON = cn(
  "inline-flex min-h-bouton items-center justify-center gap-2.5 rounded-bouton px-5 text-[17px] font-bold",
  "outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
);
const SECONDARY = cn(BUTTON, "border-2 border-input bg-card text-foreground hover:bg-voile");

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
  const format: Format = params.get("format") === "a4" ? "a4" : "ticket";
  const { timeZone } = useCompanyLocale();

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
    router.replace(next === "ticket" ? pathname : `${pathname}?format=a4`, { scroll: false });

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
      <style>{`@media print { @page { size: ${format === "a4" ? "A4" : "80mm auto"}; margin: ${format === "a4" ? "12mm" : "4mm"}; } }`}</style>
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
        "absolute left-1/2 -translate-x-1/2 -translate-y-1/2 -rotate-[18deg] border-depenses bg-card/85 tracking-[0.08em] text-depenses",
        big
          ? "top-[40%] border-4 px-6 py-2 text-[44px] font-extrabold"
          : "top-[45%] border-3 px-3.5 py-1.5 text-[22px] font-bold",
      )}
    >
      {t.cancelled}
    </div>
  );
}

function Row({
  left,
  right,
  className,
}: {
  left: ReactNode;
  right: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex justify-between gap-2", className)}>
      <span>{left}</span>
      <span>{right}</span>
    </div>
  );
}

/** Petit ticket de caisse 80 mm (maquette 05), en JetBrains Mono. */
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
  const owing = compareDecimal(receipt.balance, "0") === 1;
  const hasTax = compareDecimal(receipt.tax_total, "0") === 1;
  const dash = <div className="my-2 border-t border-dashed border-recu-encre/70" />;
  return (
    <article
      aria-label={t.title(displayNumber(receipt.sale_no))}
      className="relative w-[302px] bg-recu-papier px-4 pt-[18px] pb-6 font-receipt text-[13px] leading-normal text-recu-encre shadow-[0_2px_10px_var(--color-recu-ombre)] print:w-auto print:p-0 print:shadow-none"
    >
      <div className="text-center">
        <div className="text-base font-bold uppercase">{receipt.company.name}</div>
        {receipt.company.address && <div>{receipt.company.address}</div>}
        {receipt.company.phone && <div>{t.phone(receipt.company.phone)}</div>}
      </div>
      {dash}
      <Row
        left={t.saleNo(displayNumber(receipt.sale_no))}
        right={formatDateTime(receipt.confirmed_at ?? receipt.sold_at, timeZone)}
      />
      {receipt.customer && <div>{t.customer(receipt.customer.name)}</div>}
      {receipt.seller_name && (
        <div>{t.seller(receipt.seller_name.trim().split(/\s+/)[0] ?? "")}</div>
      )}
      {dash}
      {receipt.lines.map((line) => (
        <div key={line.product_id}>
          <div>{line.name}</div>
          <Row
            left={`  ${formatQty(line.qty)} x ${formatFigure(line.unit_price, currency)}`}
            right={formatFigure(line.line_total, currency)}
          />
        </div>
      ))}
      {dash}
      <Row
        className="text-base font-bold"
        left={t.total}
        right={formatAmount(receipt.total, currency)}
      />
      {hasTax && <Row left={t.tax(formatAmount(receipt.tax_total, currency))} right="" />}
      <Row
        left={extras.method ? t.paidWith(extras.method) : t.paid}
        right={formatAmount(receipt.paid_total, currency)}
      />
      {owing && (
        <>
          <Row
            className="font-bold"
            left={t.remaining}
            right={formatAmount(receipt.balance, currency)}
          />
          {extras.dueDate && <div>{t.payBefore(formatDate(extras.dueDate))}</div>}
        </>
      )}
      {dash}
      {receipt.company.receipt_footer && (
        <div className="text-center whitespace-pre-line">{receipt.company.receipt_footer}</div>
      )}
      <div className="mt-2 text-center text-[11px]">{t.madeWith}</div>
      {receipt.status === "cancelled" && <Stamp />}
    </article>
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

/** Facture A4 (maquette 05b) : en-tête, client, tableau, totaux et montant en lettres. */
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
  const owing = compareDecimal(receipt.balance, "0") === 1;
  const hasTax = compareDecimal(receipt.tax_total, "0") === 1;
  const ids = t.ids(receipt.company.ninea, receipt.company.rc);
  const grid = "grid grid-cols-[minmax(0,3fr)_minmax(0,1fr)_minmax(0,1.4fr)_minmax(0,1.4fr)]";
  const cell = "border-b border-recu-filet px-3 py-2.5 text-left";
  const head = cn(
    cell,
    "bg-recu-entete text-[13px] font-bold tracking-[0.04em] text-recu-gris uppercase",
  );
  return (
    <article
      aria-label={t.title(displayNumber(receipt.sale_no))}
      className="relative box-border w-[794px] max-w-full bg-recu-papier px-14 pt-14 pb-12 text-[15px] leading-normal text-recu-encre shadow-[0_2px_10px_var(--color-recu-ombre)] print:w-auto print:p-0 print:shadow-none"
    >
      <div className="flex flex-wrap justify-between gap-6">
        <div className="flex gap-3.5">
          <div className="flex size-16 shrink-0 items-center justify-center rounded-touche bg-ventes text-2xl font-extrabold text-blanc">
            {logoInitials(receipt.company.name)}
          </div>
          <div>
            <div className="text-xl font-extrabold">{receipt.company.name}</div>
            {receipt.company.address && <div>{receipt.company.address}</div>}
            {receipt.company.phone && <div>{t.phone(receipt.company.phone)}</div>}
            {ids && <div className="text-[13px] text-recu-gris">{ids}</div>}
          </div>
        </div>
        <div className="text-right">
          <div className="text-[26px] font-extrabold tracking-[0.04em]">{t.invoice}</div>
          <div>{t.invoiceNo(displayNumber(receipt.sale_no))}</div>
          <div>
            {t.invoiceDate(
              cityOf(receipt.company.address),
              formatDateLong(receipt.confirmed_at ?? receipt.sold_at, timeZone),
            )}
          </div>
        </div>
      </div>

      {receipt.customer && (
        <div className="mt-7 mb-5 max-w-80 rounded-[10px] border border-recu-filet px-4 py-3.5">
          <div className="text-[13px] tracking-[0.04em] text-recu-gris uppercase">
            {t.customerTitle}
          </div>
          <div className="text-[17px] font-bold">{receipt.customer.name}</div>
          {receipt.customer.phone && <div>{t.phone(receipt.customer.phone)}</div>}
        </div>
      )}

      <div className={grid}>
        <div className={head}>{t.columns.article}</div>
        <div className={cn(head, "text-right")}>{t.columns.qty}</div>
        <div className={cn(head, "text-right")}>{t.columns.price}</div>
        <div className={cn(head, "text-right")}>{t.columns.amount}</div>
      </div>
      {receipt.lines.map((line) => (
        <div key={line.product_id} className={grid}>
          <div className={cell}>{line.name}</div>
          <div className={cn(cell, "text-right numeric")}>{formatQty(line.qty)}</div>
          <div className={cn(cell, "text-right numeric")}>
            {formatAmount(line.unit_price, currency)}
          </div>
          <div className={cn(cell, "text-right numeric")}>
            {formatAmount(line.line_total, currency)}
          </div>
        </div>
      ))}

      <div className="mt-4 flex justify-end">
        <div className="w-[300px]">
          <div className="flex justify-between border-b-2 border-recu-encre py-2 text-lg font-extrabold">
            <span>{t.invoiceTotal}</span>
            <span className="numeric">{formatAmount(receipt.total, currency)}</span>
          </div>
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

      <p className="mt-6">
        {t.inWords}
        <strong>{amountInWords(receipt.total)}</strong>.
      </p>
      <p className="mt-1.5 text-recu-gris">
        {hasTax ? t.vatIncluded(formatAmount(receipt.tax_total, currency)) : t.noVat}
        {owing && extras.dueDate && ` ${t.remainingBefore(formatDateLong(extras.dueDate))}`}
      </p>

      <div className="mt-12 flex flex-wrap justify-between gap-6">
        <div className="text-recu-gris">
          {t.thanks}
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
      </div>
      {receipt.status === "cancelled" && <Stamp big />}
    </article>
  );
}
