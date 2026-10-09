"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Printer } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { ErrorState } from "@/components/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { useCompanyLocale } from "@/hooks/use-me";
import { api, unwrap } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries/keys";
import { compareDecimal } from "@/lib/decimal";
import { formatAmount, formatDateTime, formatFigure, formatQty } from "@/lib/format";
import { labels } from "@/lib/labels";
import { displayNumber } from "@/lib/units";
import { cn } from "@/lib/utils";

const t = labels.receipt;

const BUTTON = cn(
  "inline-flex min-h-bouton items-center justify-center gap-2.5 rounded-bouton px-5 text-[17px] font-bold",
  "outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
);

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

/**
 * Bon de retour, sur le gabarit du petit ticket 80 mm (maquette 05) : la boutique, le
 * retour et sa vente, les articles rendus, la valeur rendue et ce qui en a été réglé.
 */
export function ReturnSlipView({ returnId }: { returnId: string }) {
  const { timeZone } = useCompanyLocale();
  const saleReturn = useQuery({
    queryKey: queryKeys.saleReturns.detail(returnId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/sale-returns/{return_id}", {
          params: { path: { return_id: returnId } },
        }),
      ),
  });
  const saleId = saleReturn.data?.sale_id;
  const receipt = useQuery({
    queryKey: queryKeys.sales.receipt(saleId ?? "aucune"),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/sales/{sale_id}/receipt", { params: { path: { sale_id: saleId! } } }),
      ),
    enabled: Boolean(saleId),
  });
  const sale = useQuery({
    queryKey: queryKeys.sales.detail(saleId ?? "aucune"),
    queryFn: () =>
      unwrap(api.GET("/api/v1/sales/{sale_id}", { params: { path: { sale_id: saleId! } } })),
    enabled: Boolean(saleId),
  });

  const error = saleReturn.error ?? receipt.error ?? sale.error;
  const data = saleReturn.data;
  const shop = receipt.data;
  const names = new Map(sale.data?.items.map((item) => [item.id, item]));
  const currency = shop?.company.currency ?? "XOF";
  const dash = <div className="my-2 border-t border-dashed border-recu-encre/70" />;

  return (
    <div className="mx-auto flex max-w-page flex-col gap-[18px]">
      <style>{"@media print { @page { size: 80mm auto; margin: 4mm; } }"}</style>
      <div className="flex flex-wrap items-center gap-3 print:hidden">
        {saleId && (
          <Link
            href={`/sales/${saleId}`}
            className={cn(BUTTON, "border-2 border-input bg-card text-foreground hover:bg-voile")}
          >
            <ArrowLeft className="size-[22px]" aria-hidden />
            {t.slip.back}
          </Link>
        )}
        <h1 className="flex-[1_1_240px] text-[28px] leading-[1.45] font-extrabold">
          {data ? t.slip.title(displayNumber(data.return_no)) : " "}
        </h1>
        <button
          type="button"
          onClick={() => window.print()}
          disabled={!shop}
          className={cn(BUTTON, "bg-ventes text-primary-foreground hover:bg-ventes/90")}
        >
          <Printer className="size-[22px]" aria-hidden />
          {t.print}
        </button>
      </div>
      <div className="flex justify-center rounded-carte bg-recu-fond px-4 py-8 print:block print:bg-transparent print:p-0">
        {error ? (
          <ErrorState error={error} onRetry={() => void saleReturn.refetch()} />
        ) : !data || !shop || !sale.data ? (
          <Skeleton className="h-[420px] w-[302px]" />
        ) : (
          <article
            aria-label={t.slip.title(displayNumber(data.return_no))}
            className="w-[302px] bg-recu-papier px-4 pt-[18px] pb-6 font-receipt text-[13px] leading-normal text-recu-encre shadow-[0_2px_10px_var(--color-recu-ombre)] print:w-auto print:p-0 print:shadow-none"
          >
            <div className="text-center">
              <div className="text-base font-bold uppercase">{shop.company.name}</div>
              {shop.company.address && <div>{shop.company.address}</div>}
              {shop.company.phone && <div>{t.phone(shop.company.phone)}</div>}
            </div>
            {dash}
            <div className="text-center font-bold">{t.slip.heading}</div>
            <Row
              left={t.slip.returnNo(displayNumber(data.return_no))}
              right={formatDateTime(data.returned_at, timeZone)}
            />
            <div>{t.slip.ofSale(displayNumber(shop.sale_no))}</div>
            {shop.customer && <div>{t.customer(shop.customer.name)}</div>}
            {data.reason && <div>{t.slip.why(data.reason)}</div>}
            {dash}
            {data.items.map((line) => {
              const item = names.get(line.sale_item_id);
              return (
                <div key={line.id}>
                  <div>{item?.product_name ?? labels.sales.deletedProduct}</div>
                  <Row
                    left={`  ${formatQty(line.qty)} x ${formatFigure(item?.unit_price, currency)}`}
                    right={formatFigure(line.refund_amount, currency)}
                  />
                </div>
              );
            })}
            {dash}
            <Row
              className="text-base font-bold"
              left={t.slip.value}
              right={formatAmount(data.total_refund, currency)}
            />
            {data.payments
              .filter((payment) => !payment.cancelled && !payment.reversal_of_payment_id)
              .map((payment) => (
                <Row
                  key={payment.id}
                  left={t.slip.settled(labels.paymentMethods[payment.method])}
                  right={formatAmount(payment.amount, currency)}
                />
              ))}
            {compareDecimal(data.refund_due, "0") === 1 && (
              <Row
                className="font-bold"
                left={t.slip.toGive}
                right={formatAmount(data.refund_due, currency)}
              />
            )}
            {dash}
            <div className="mt-2 text-center text-[11px]">{t.madeWith}</div>
          </article>
        )}
      </div>
    </div>
  );
}
