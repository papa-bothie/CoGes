"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";

import { ErrorState } from "@/components/error-state";
import { RUBRIQUE_CLASSES } from "@/components/kit/rubrique";
import { HistoryTabs, PersonHeader, SheetTile } from "@/components/people/person-sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { useCompanyLocale } from "@/hooks/use-me";
import { usePermission } from "@/hooks/use-permission";
import { api, unwrap } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries/keys";
import { compareDecimal } from "@/lib/decimal";
import { formatAmount, formatClock } from "@/lib/format";
import { labels } from "@/lib/labels";
import { dueDay, monthYear, shortNames, visitDay } from "@/lib/people";
import { cn } from "@/lib/utils";

const t = labels.peopleScreens.supplier;
const methods = labels.peopleScreens.methods;
const ACTION = cn(
  "inline-flex min-h-bouton flex-[1_1_220px] items-center justify-center gap-2.5 rounded-bouton px-5 text-[17px] font-bold",
  "outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
);
const ROW = "flex flex-wrap items-center gap-x-3.5 gap-y-2.5 border-t border-filet py-3.5";
const PILL =
  "inline-flex min-w-[130px] items-center justify-center rounded-full px-3 py-1.5 text-[15px] font-bold numeric whitespace-nowrap";

/**
 * La fiche fournisseur, maquette v2 (écran 16) : ce que vous lui devez et avant quand, ce
 * que vous lui avez acheté ce mois, ce qu'il livre ; le payer, recevoir une livraison ;
 * puis ses livraisons et vos paiements. « Le payer » ouvre l'écran 19, le
 * fournisseur choisi (ADR 0073).
 */
export function SupplierDetailView({ supplierId }: { supplierId: string }) {
  const { timeZone, currency } = useCompanyLocale();
  const money = usePermission("debts:read");
  const canReadPayments = usePermission("payments:read");
  const canPay = usePermission("payments:create");
  const sheet = useQuery({
    queryKey: queryKeys.people.sheet("supplier", supplierId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/analytics/suppliers/{supplier_id}", {
          params: { path: { supplier_id: supplierId } },
        }),
      ),
  });

  if (sheet.isError) {
    return <ErrorState error={sheet.error} onRetry={() => void sheet.refetch()} />;
  }
  if (!sheet.data) return <Skeleton className="mx-auto h-96 w-full max-w-page rounded-carte" />;
  const data = sheet.data;
  const owes = data.owed !== null && compareDecimal(data.owed, "0") === 1;

  return (
    <div className="mx-auto flex max-w-page flex-col gap-5">
      <Link
        href="/suppliers"
        className="inline-flex min-h-11 items-center gap-2 self-start font-bold text-foreground hover:underline pointer-coarse:min-h-12"
      >
        <ArrowLeft className="size-[22px]" aria-hidden />
        {labels.people.back.supplier}
      </Link>

      <PersonHeader
        name={data.name}
        rubrique="argent"
        subtitle={t.subtitle(data.phone, data.address, monthYear(data.created_at, timeZone))}
        phone={data.phone}
        editHref={`/suppliers/${supplierId}/edit`}
        editPermission="suppliers:update"
      />

      <div className="grid grid-cols-[repeat(auto-fit,minmax(220px,1fr))] gap-3">
        {data.owed !== null && (
          <SheetTile
            rubrique="argent"
            label={t.owed}
            value={owes ? formatAmount(data.owed, currency) : t.nothing}
            detail={
              owes ? (data.due_date ? t.before(dueDay(data.due_date)) : t.noDue) : t.nothingToPay
            }
            detailInk={owes ? "text-stock-encre" : undefined}
          />
        )}
        {data.month_total !== null && (
          <SheetTile
            rubrique="stock"
            label={t.month}
            value={formatAmount(data.month_total, currency)}
            detail={t.deliveries(data.month_deliveries)}
          />
        )}
        <SheetTile
          label={t.articles}
          value={data.product_count ? shortNames(data.product_names) : t.noArticle}
          detail={data.product_count ? t.articleCount(data.product_count) : null}
          small
        />
      </div>

      <div className="flex flex-wrap gap-2.5">
        {money && owes && canPay && (
          <Link
            href={`/finance/pay?supplier=${supplierId}`}
            className={cn(ACTION, RUBRIQUE_CLASSES.argent.solid)}
          >
            {t.pay}
          </Link>
        )}
        <Link
          href={`/inventory/receive?supplier=${supplierId}`}
          className={cn(ACTION, RUBRIQUE_CLASSES.stock.solid)}
        >
          {t.receive}
        </Link>
      </div>

      {(money || canReadPayments) && (
        <HistoryTabs
          rubrique="argent"
          label={t.tabs}
          tabs={[
            ...(money
              ? [
                  {
                    id: "deliveries",
                    label: t.deliveriesTab,
                    content: (
                      <Deliveries supplierId={supplierId} currency={currency} timeZone={timeZone} />
                    ),
                  },
                ]
              : []),
            ...(canReadPayments
              ? [
                  {
                    id: "payments",
                    label: t.payments,
                    content: (
                      <Payments supplierId={supplierId} currency={currency} timeZone={timeZone} />
                    ),
                  },
                ]
              : []),
          ]}
        />
      )}
    </div>
  );
}

type Locale = { currency: string; timeZone: string };

function Deliveries({ supplierId, currency, timeZone }: { supplierId: string } & Locale) {
  const deliveries = useQuery({
    queryKey: queryKeys.people.history("supplier", supplierId, "deliveries"),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/analytics/suppliers/{supplier_id}/deliveries", {
          params: { path: { supplier_id: supplierId } },
        }),
      ),
  });
  if (deliveries.isError) {
    return <ErrorState error={deliveries.error} onRetry={() => void deliveries.refetch()} />;
  }
  if (!deliveries.data) return <Skeleton className="h-40 w-full" />;
  if (deliveries.data.items.length === 0) {
    return <p className="border-t border-filet py-4 text-muted-foreground">{t.noDeliveries}</p>;
  }
  return (
    <ul>
      {deliveries.data.items.map((delivery) => {
        const due = compareDecimal(delivery.balance, "0") === 1;
        const writtenOff = delivery.status === "written_off";
        return (
          <li key={delivery.debt_id} className={ROW}>
            <span className="min-w-0 flex-[1_1_220px]">
              <span className="block font-bold">
                {t.deliveryLine(shortNames(delivery.lines.map((line) => line.name)))}
              </span>
              <span className="block text-muted-foreground">
                {historyDay(delivery.created_at, timeZone)}
              </span>
            </span>
            <span className="text-lg font-extrabold numeric">
              {formatAmount(delivery.total, currency)}
            </span>
            <span
              className={cn(
                PILL,
                writtenOff
                  ? "bg-voile text-encre-2"
                  : due
                    ? "bg-argent-teinte text-argent-encre"
                    : "bg-ventes-teinte text-ventes-encre",
              )}
            >
              {writtenOff
                ? labels.kit.status.writtenOff
                : due
                  ? labels.kit.status.remaining(formatAmount(delivery.balance, currency))
                  : labels.kit.status.paid}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

function Payments({ supplierId, currency, timeZone }: { supplierId: string } & Locale) {
  const payments = useQuery({
    queryKey: queryKeys.people.history("supplier", supplierId, "payments"),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/analytics/suppliers/{supplier_id}/payments", {
          params: { path: { supplier_id: supplierId } },
        }),
      ),
  });
  if (payments.isError) {
    return <ErrorState error={payments.error} onRetry={() => void payments.refetch()} />;
  }
  if (!payments.data) return <Skeleton className="h-40 w-full" />;
  if (payments.data.items.length === 0) {
    return <p className="border-t border-filet py-4 text-muted-foreground">{t.noPayments}</p>;
  }
  return (
    <ul>
      {payments.data.items.map((payment) => (
        <li key={payment.payment_id} className={ROW}>
          <span className="min-w-0 flex-[1_1_220px]">
            <span className="block font-bold">{t.paidAt(methods[payment.method] ?? "")}</span>
            <span className="block text-muted-foreground">
              {historyDay(payment.paid_at, timeZone)}
            </span>
          </span>
          <span className="text-lg font-extrabold numeric">
            {formatAmount(payment.amount, currency)}
          </span>
          {payment.debt_created_at && (
            <span className={cn(PILL, "bg-voile text-encre-2")}>
              {t.deliveryOf(dueDay(payment.debt_created_at.slice(0, 10)))}
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}

/** « Aujourd'hui, 9 h 58 », « Samedi 3 octobre » : le jour d'une ligne d'historique. */
function historyDay(value: string, timeZone: string): string {
  const day = visitDay(value, timeZone);
  return day === "Aujourd'hui" || day === "Hier" ? `${day}, ${formatClock(value, timeZone)}` : day;
}
