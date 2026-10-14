"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CircleX, CreditCard, MessageCircle, Printer, Undo2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { toast } from "sonner";

import { ErrorState } from "@/components/error-state";
import { FieldError } from "@/components/field-error";
import { ProductSquare } from "@/components/kit/list-row";
import { StatusPill } from "@/components/kit/status-pill";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useCompanyLocale, useMe } from "@/hooks/use-me";
import { Can, usePermission } from "@/hooks/use-permission";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { compareDecimal } from "@/lib/decimal";
import { formatAmount, formatClock, formatDate, formatDayMonth, formatQty } from "@/lib/format";
import { labels } from "@/lib/labels";
import { addDays, todayIn } from "@/lib/period";
import { salePill } from "@/lib/sale-status";
import { displayNumber } from "@/lib/units";
import { cn } from "@/lib/utils";
import { receiptText, whatsappLink } from "@/lib/whatsapp";

type SaleDetail = Schemas["SaleDetail"];

const t = labels.sales.detail;

/** « Aujourd'hui », « Hier », sinon « Le 04/10/2026 » : le jour d'un instant, dans le fuseau. */
function relativeDay(value: string, timeZone: string): string {
  const today = todayIn(timeZone);
  const day = todayIn(timeZone, new Date(value));
  if (day === today) return t.today;
  if (day === addDays(today, -1)) return t.yesterday;
  return t.onDay(formatDate(value, timeZone));
}

const TILE = cn(
  "flex min-h-24 flex-[1_1_150px] flex-col items-center justify-center gap-2 rounded-[18px] border-2 border-input bg-card p-2.5 text-center font-bold text-foreground",
  "outline-none hover:border-ventes hover:text-ventes-encre focus-visible:ring-3 focus-visible:ring-ring/50",
);

/**
 * Détail d'une vente, maquette v2 (écran 04) : numéro, quand et par qui, pastille d'état ;
 * gros boutons-tuiles (reçu, WhatsApp, encaisser le reste, retour, annuler) ; les articles
 * à gauche, l'argent à droite. Annuler demande la raison en boutons (04b). Un brouillon se
 * reprend dans « Nouvelle vente ».
 */
export function SaleDetailView({ saleId }: { saleId: string }) {
  const router = useRouter();
  const { timeZone, currency } = useCompanyLocale();
  const { data: me } = useMe();
  const [asking, setAsking] = useState(false);
  const canCollect = usePermission("payments:create");

  const sale = useQuery({
    queryKey: queryKeys.sales.detail(saleId),
    queryFn: () =>
      unwrap(api.GET("/api/v1/sales/{sale_id}", { params: { path: { sale_id: saleId } } })),
  });
  const data = sale.data;
  const returns = useQuery({
    queryKey: queryKeys.sales.returns(saleId),
    queryFn: () =>
      unwrap(api.GET("/api/v1/sales/{sale_id}/returns", { params: { path: { sale_id: saleId } } })),
    enabled: data?.has_returns ?? false,
  });
  const customerId = data?.customer_id ?? null;
  const customer = useQuery({
    queryKey: queryKeys.customers.detail(customerId ?? "aucun"),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/customers/{customer_id}", {
          params: { path: { customer_id: customerId! } },
        }),
      ),
    enabled: customerId !== null,
  });

  useEffect(() => {
    if (data?.status === "draft") router.replace(`/sales/${data.id}/edit`);
  }, [data, router]);

  if (sale.isError) return <ErrorState error={sale.error} onRetry={() => void sale.refetch()} />;
  if (!data || data.status === "draft") return <DetailSkeleton />;

  const pill = salePill(data, currency);
  const cancelled = data.status === "cancelled";
  const owing = compareDecimal(data.balance, "0") === 1 && data.debt?.status !== "written_off";
  const returnable = data.items.some((item) => compareDecimal(item.qty, item.returned_qty) === 1);
  const phone = customer.data?.phone ?? null;
  const text = receiptText(data, { shop: me?.company.name ?? "", timeZone, currency });
  const seller = data.seller_name?.trim().split(/\s+/)[0];
  const livePayments = data.payments.filter((payment) => !payment.reversal_of_payment_id);

  return (
    <div className="mx-auto flex max-w-page flex-col gap-5">
      <Link
        href="/sales"
        className="inline-flex min-h-11 items-center gap-2 self-start font-bold text-ventes hover:text-ventes-encre pointer-coarse:min-h-12"
      >
        <ArrowLeft className="size-[22px]" aria-hidden />
        {labels.sales.backToList}
      </Link>

      <div className="flex flex-wrap items-center gap-4">
        <div className="flex-[1_1_300px]">
          <h1
            className={cn(
              "text-titre-page leading-[1.45] tracking-[-0.01em]",
              cancelled && "line-through",
            )}
          >
            {t.title(displayNumber(data.sale_no))}
          </h1>
          <p className="text-lg text-muted-foreground">
            {t.when(relativeDay(data.sold_at, timeZone), formatClock(data.sold_at, timeZone))}
            {seller && ` · ${t.servedBy(seller)}`}
          </p>
        </div>
        {pill && (
          <StatusPill
            status={pill.status}
            amount={pill.amount}
            className="px-[18px] py-2.5 text-lg"
          />
        )}
      </div>

      {cancelled && (
        <p className="rounded-[18px] bg-voile px-[18px] py-4 text-libelle">
          {t.cancelledBanner((data.cancel_reason ?? "").toLocaleLowerCase("fr-FR"))}
        </p>
      )}

      {!cancelled && !asking && (
        <div className="flex flex-wrap gap-2.5">
          <Link href={`/sales/${data.id}/receipt`} className={TILE}>
            <Printer className="size-7" aria-hidden />
            {t.print}
          </Link>
          <a
            href={whatsappLink(text, phone)}
            target="_blank"
            rel="noopener noreferrer"
            className={TILE}
          >
            <MessageCircle className="size-7" aria-hidden />
            {labels.whatsapp.send}
          </a>
          {owing && canCollect && (
            <Link
              href={`/finance/collect?customer=${data.customer_id ?? ""}`}
              className={cn(TILE, "border-clients-anneau bg-clients-teinte text-clients-encre")}
            >
              <CreditCard className="size-7" aria-hidden />
              {t.collect}
            </Link>
          )}
          {returnable && (
            <Can permission="sale_returns:create">
              <Link href={`/sales/${data.id}/returns/new`} className={TILE}>
                <Undo2 className="size-7" aria-hidden />
                {t.returnItems}
              </Link>
            </Can>
          )}
          <Can permission="sales:cancel">
            <button
              type="button"
              onClick={() => setAsking(true)}
              className={cn(TILE, "border-depenses-anneau text-depenses-encre")}
            >
              <CircleX className="size-7" aria-hidden />
              {t.cancel}
            </button>
          </Can>
        </div>
      )}

      {asking && <CancelCard sale={data} onDone={() => setAsking(false)} />}

      <div className="flex flex-wrap items-start gap-5">
        <section className="min-w-0 flex-[3_1_480px] rounded-carte border border-border bg-card p-carte">
          <div className="mb-2 flex items-center gap-3">
            <span
              aria-hidden
              className="flex size-12 shrink-0 items-center justify-center rounded-full bg-clients font-bold text-primary-foreground"
            >
              {data.customer_name ? initialsOf(data.customer_name) : "·"}
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-lg font-bold">{data.customer_name ?? labels.sales.anonymous}</p>
              <p className="numeric text-muted-foreground">
                {data.customer_name ? (phone ?? " ") : t.walkInHint}
              </p>
            </div>
            {customerId && (
              <Link
                href={`/customers/${customerId}`}
                className="font-bold text-ventes underline underline-offset-2 hover:text-ventes-encre"
              >
                {t.seeCustomer}
              </Link>
            )}
          </div>
          {data.items.map((item) => (
            <div key={item.id} className="flex items-center gap-3 border-t border-filet py-3">
              <ProductSquare name={item.product_name ?? "?"} size="petit" />
              <div className="min-w-0 flex-1">
                <p className="font-bold">{item.product_name ?? labels.sales.deletedProduct}</p>
                <p className="numeric text-muted-foreground">
                  {t.lineQty(formatQty(item.qty), formatAmount(item.unit_price, currency))}
                </p>
              </div>
              <span className="text-lg font-extrabold numeric">
                {formatAmount(item.line_total, currency)}
              </span>
            </div>
          ))}
          {(returns.data?.items.length ?? 0) > 0 && (
            <div className="border-t border-filet pt-3">
              <p className="mb-1 font-bold">{t.returns}</p>
              {returns.data?.items.map((item) => (
                <Link
                  key={item.id}
                  href={`/sales/returns/${item.id}`}
                  className="flex min-h-12 items-center justify-between gap-3 rounded-mini px-1 hover:bg-muted"
                >
                  <span>
                    {t.returnLine(
                      displayNumber(item.return_no),
                      formatDate(item.returned_at, timeZone),
                    )}
                  </span>
                  <span className="text-right">
                    <span className="block font-bold numeric">
                      {formatAmount(item.total_refund, currency)}
                    </span>
                    <span className="block text-sm text-muted-foreground">
                      {labels.returns.refundStatus[item.refund_status]}
                    </span>
                  </span>
                </Link>
              ))}
            </div>
          )}
        </section>

        <section className="flex min-w-0 flex-[2_1_320px] flex-col gap-3 rounded-carte border border-border bg-card p-carte">
          <div className="flex items-baseline justify-between rounded-champ bg-ventes-teinte px-4 py-3.5">
            <span className="text-lg font-bold">{t.total}</span>
            <span className="text-[30px] leading-tight font-extrabold numeric text-ventes-encre">
              {formatAmount(data.total, currency)}
            </span>
          </div>
          <MoneyRow label={t.paid} value={formatAmount(data.paid_total, currency)} />
          {owing && (
            <MoneyRow
              label={t.remaining}
              value={formatAmount(data.balance, currency)}
              className="text-stock-encre"
              strong
            />
          )}
          {livePayments.length > 0 && (
            <div className="border-t border-filet pt-3">
              <p className="mb-1.5 font-bold">{t.paymentsReceived}</p>
              {livePayments.map((payment) => (
                <div
                  key={payment.id}
                  className={cn(
                    "flex justify-between gap-2 py-2",
                    payment.cancelled && "text-muted-foreground line-through",
                  )}
                >
                  <span>
                    {t.paymentLine(
                      `${relativeDay(payment.paid_at, timeZone)}, ${formatClock(payment.paid_at, timeZone)}`,
                      labels.paymentMethods[payment.method],
                    )}
                  </span>
                  <span className="font-bold numeric">
                    {formatAmount(payment.amount, currency)}
                  </span>
                </div>
              ))}
            </div>
          )}
          {owing && data.debt?.due_date && (
            <div className="border-t border-filet pt-3">
              <p className="font-bold">{t.payBefore}</p>
              <p className="text-lg numeric">{formatDayMonth(data.debt.due_date, timeZone)}</p>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function initialsOf(name: string): string {
  return name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((word) => word.charAt(0).toLocaleUpperCase("fr-FR"))
    .join("");
}

function MoneyRow({
  label,
  value,
  className,
  strong = false,
}: {
  label: string;
  value: ReactNode;
  className?: string;
  strong?: boolean;
}) {
  return (
    <div className={cn("flex justify-between px-1 text-lg", className)}>
      <span className={strong ? "font-bold" : "font-semibold"}>{label}</span>
      <span className="font-extrabold numeric">{value}</span>
    </div>
  );
}

/** « Pourquoi annuler cette vente ? » : raisons en boutons, puis oui ou non (maquette 04b). */
function CancelCard({ sale, onDone }: { sale: SaleDetail; onDone: () => void }) {
  const queryClient = useQueryClient();
  const [reason, setReason] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const cancel = useMutation({
    meta: { toastError: false },
    mutationFn: (why: string) =>
      unwrap(
        api.POST("/api/v1/sales/{sale_id}/cancel", {
          params: { path: { sale_id: sale.id } },
          body: { reason: why },
        }),
      ),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.sales.detail(updated.id), updated);
      for (const key of [queryKeys.sales.all, queryKeys.stock.all, queryKeys.dashboard]) {
        void queryClient.invalidateQueries({ queryKey: key });
      }
      toast.success(labels.sales.cancelledToast(displayNumber(updated.sale_no)));
      onDone();
    },
    onError: (failure) => setError(errorMessage(failure)),
  });

  return (
    <section className="flex flex-col gap-3.5 rounded-carte border-2 border-depenses-anneau bg-card p-5">
      <h2 className="text-titre-carte text-depenses-encre">{t.cancelQuestion}</h2>
      <div role="group" aria-label={t.cancelQuestion} className="flex flex-wrap gap-2">
        {t.cancelReasons.map((label) => (
          <button
            key={label}
            type="button"
            aria-pressed={reason === label}
            onClick={() => setReason(label)}
            className={cn(
              "min-h-14 flex-[1_1_200px] rounded-champ border-2 px-[18px] font-bold",
              "outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
              reason === label
                ? "border-depenses bg-depenses-teinte text-depenses-encre"
                : "border-input bg-card text-foreground hover:bg-voile",
            )}
          >
            {label}
          </button>
        ))}
      </div>
      <FieldError message={error} />
      <div className="flex flex-wrap gap-2.5">
        <Button
          variant="depenses"
          size="standard"
          className="flex-[1_1_220px] text-lg disabled:bg-depenses/45 disabled:opacity-100"
          disabled={!reason || cancel.isPending}
          onClick={() => reason && cancel.mutate(reason)}
        >
          {t.cancelYes}
        </Button>
        <Button
          variant="secondaire"
          size="standard"
          className="flex-[1_1_220px] text-lg"
          onClick={onDone}
        >
          {t.cancelNo}
        </Button>
      </div>
    </section>
  );
}

function DetailSkeleton() {
  return (
    <div className="mx-auto max-w-page space-y-5">
      <Skeleton className="h-11 w-48" />
      <Skeleton className="h-14 w-72" />
      <Skeleton className="h-24 w-full" />
      <div className="flex flex-wrap gap-5">
        <Skeleton className="h-72 flex-[3_1_480px]" />
        <Skeleton className="h-72 flex-[2_1_320px]" />
      </div>
    </div>
  );
}
