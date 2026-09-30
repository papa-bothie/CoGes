"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Printer } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { ErrorState } from "@/components/error-state";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useCompanyLocale, useMe } from "@/hooks/use-me";
import { api, unwrap } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { compareDecimal } from "@/lib/decimal";
import { formatDateTime, formatMoney, formatQty } from "@/lib/format";
import { labels } from "@/lib/labels";
import { cn } from "@/lib/utils";

type Receipt = Schemas["ReceiptRead"];
type Format = "ticket" | "a4";

/**
 * Reçu imprimable. Le contenu vient de `GET /sales/{id}/receipt` (montants figés à la
 * confirmation, ADR 0022) ; seule la mise en page change entre le ticket 80 mm et l'A4.
 * La règle `@page` suit le format choisi : l'impression part sans réglage manuel.
 */
export function ReceiptView({ saleId }: { saleId: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const format: Format = params.get("format") === "a4" ? "a4" : "ticket";
  const { timeZone } = useCompanyLocale();
  const { data: me } = useMe();
  const showTax = me?.company.tax_enabled ?? true;

  const receipt = useQuery({
    queryKey: queryKeys.sales.receipt(saleId),
    queryFn: () =>
      unwrap(api.GET("/api/v1/sales/{sale_id}/receipt", { params: { path: { sale_id: saleId } } })),
  });

  const setFormat = (next: Format) =>
    router.replace(next === "ticket" ? pathname : `${pathname}?format=a4`, { scroll: false });

  return (
    <>
      <style>{`@media print { @page { size: ${format === "a4" ? "A4" : "80mm auto"}; margin: ${format === "a4" ? "15mm" : "4mm"}; } }`}</style>
      <div className="flex flex-wrap items-center justify-between gap-3 print:hidden">
        <Link
          href={`/sales/${saleId}`}
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" aria-hidden />
          {labels.receipt.back}
        </Link>
        <div className="flex items-center gap-2">
          <div
            role="radiogroup"
            aria-label={labels.receipt.format}
            className="grid grid-cols-2 gap-1 rounded-lg bg-muted p-1"
          >
            {(["ticket", "a4"] as const).map((value) => (
              <button
                key={value}
                type="button"
                role="radio"
                aria-checked={format === value}
                onClick={() => setFormat(value)}
                className={cn(
                  "rounded-md px-3 py-1 text-sm font-medium outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                  format === value
                    ? "bg-card text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {value === "ticket" ? labels.receipt.ticket : labels.receipt.a4}
              </button>
            ))}
          </div>
          <Button onClick={() => window.print()} disabled={!receipt.data}>
            <Printer aria-hidden />
            {labels.receipt.print}
          </Button>
        </div>
      </div>

      {receipt.isError ? (
        <ErrorState error={receipt.error} onRetry={() => void receipt.refetch()} />
      ) : !receipt.data ? (
        <Skeleton className="mx-auto h-[480px] w-[80mm]" />
      ) : (
        <ReceiptSheet
          receipt={receipt.data}
          format={format}
          timeZone={timeZone}
          showTax={showTax}
        />
      )}
    </>
  );
}

function ReceiptSheet({
  receipt,
  format,
  timeZone,
  showTax,
}: {
  receipt: Receipt;
  format: Format;
  timeZone: string;
  showTax: boolean;
}) {
  const money = (value: string) => formatMoney(value, receipt.company.currency);
  const ticket = format === "ticket";
  const hasBalance = compareDecimal(receipt.balance, "0") === 1;

  return (
    <article
      aria-label={labels.receipt.title(receipt.sale_no)}
      className={cn(
        "mx-auto bg-white text-black shadow-sm ring-1 ring-border print:shadow-none print:ring-0",
        ticket
          ? "w-[80mm] px-4 py-5 font-mono text-[12px] leading-snug print:w-auto print:p-0"
          : "w-[210mm] max-w-full px-12 py-10 text-sm print:w-auto print:p-0",
      )}
    >
      <header className={cn(ticket ? "text-center" : "flex items-start justify-between")}>
        <div>
          <p className={cn("font-bold", ticket ? "text-base" : "text-xl")}>
            {receipt.company.name}
          </p>
          <p className="numeric">{labels.receipt.title(receipt.sale_no)}</p>
        </div>
        <div className={cn(ticket ? "mt-1" : "text-right")}>
          <p className="numeric">
            {labels.receipt.date} :{" "}
            {formatDateTime(receipt.confirmed_at ?? receipt.sold_at, timeZone)}
          </p>
          {receipt.customer && (
            <p>
              {labels.receipt.customer} : {receipt.customer.name}
              {receipt.customer.code && ` (${receipt.customer.code})`}
            </p>
          )}
        </div>
      </header>

      {receipt.status === "cancelled" && (
        <p className="my-3 border-2 border-black py-1 text-center font-bold tracking-widest">
          {labels.receipt.cancelled}
        </p>
      )}

      <table className={cn("w-full border-collapse", ticket ? "mt-3" : "mt-8")}>
        <thead>
          <tr className="border-y border-black text-left">
            <th className="py-1 font-semibold">{labels.sales.lineColumns.product}</th>
            {!ticket && (
              <th className="py-1 text-right font-semibold">{labels.sales.lineColumns.qty}</th>
            )}
            {!ticket && (
              <th className="py-1 text-right font-semibold">
                {labels.sales.lineColumns.unitPrice}
              </th>
            )}
            {!ticket && (
              <th className="py-1 text-right font-semibold">{labels.sales.lineColumns.discount}</th>
            )}
            {!ticket && showTax && (
              <th className="py-1 text-right font-semibold">{labels.sales.lineColumns.tax}</th>
            )}
            <th className="py-1 text-right font-semibold">{labels.sales.lineColumns.total}</th>
          </tr>
        </thead>
        <tbody>
          {receipt.lines.map((line) => (
            <tr key={line.product_id} className="align-top">
              <td className="py-1 pr-2">
                {line.name}
                {ticket && (
                  <span className="block text-[11px] numeric">
                    {formatQty(line.qty)} × {money(line.unit_price)}
                    {compareDecimal(line.discount, "0") === 1 && ` − ${money(line.discount)}`}
                  </span>
                )}
              </td>
              {!ticket && <td className="py-1 pl-3 text-right numeric">{formatQty(line.qty)}</td>}
              {!ticket && (
                <td className="py-1 pl-3 text-right numeric">{money(line.unit_price)}</td>
              )}
              {!ticket && <td className="py-1 pl-3 text-right numeric">{money(line.discount)}</td>}
              {!ticket && showTax && (
                <td className="py-1 pl-3 text-right numeric">{money(line.tax_amount)}</td>
              )}
              <td className="py-1 text-right numeric whitespace-nowrap">
                {money(line.line_total)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <dl className={cn("mt-3 space-y-0.5 border-t border-black pt-2", !ticket && "ml-auto w-72")}>
        <Line label={labels.sales.subtotal} value={money(receipt.subtotal)} />
        <Line label={labels.sales.discounts} value={money(receipt.discount_total)} />
        {showTax && <Line label={labels.sales.taxes} value={money(receipt.tax_total)} />}
        <Line label={labels.sales.total} value={money(receipt.total)} strong />
        <Line label={labels.sales.paid} value={money(receipt.paid_total)} />
        {hasBalance && <Line label={labels.sales.due} value={money(receipt.balance)} strong />}
      </dl>

      {receipt.payments.length > 0 && (
        <ul className="mt-3 space-y-0.5">
          {receipt.payments
            .filter((payment) => !payment.cancelled && payment.direction === "inflow")
            .map((payment) => (
              <li key={payment.id} className="flex justify-between">
                <span>{labels.paymentMethods[payment.method]}</span>
                <span className="numeric">{money(payment.amount)}</span>
              </li>
            ))}
        </ul>
      )}

      <p className={cn("mt-5", ticket && "text-center")}>{labels.receipt.thanks}</p>
    </article>
  );
}

function Line({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className={cn("flex justify-between gap-3", strong && "font-bold")}>
      <dt>{label}</dt>
      <dd className="numeric whitespace-nowrap">{value}</dd>
    </div>
  );
}
