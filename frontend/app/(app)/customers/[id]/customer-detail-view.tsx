"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, MessageCircle } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { ErrorState } from "@/components/error-state";
import { RUBRIQUE_CLASSES } from "@/components/kit/rubrique";
import { StatusPill } from "@/components/kit/status-pill";
import { HistoryTabs, PersonHeader, SheetTile } from "@/components/people/person-sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { useCompanyLocale, useMe } from "@/hooks/use-me";
import { usePermission } from "@/hooks/use-permission";
import { withFrom } from "@/lib/back-target";
import { api, unwrap } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries/keys";
import { compareDecimal } from "@/lib/decimal";
import { formatAmount, formatClock } from "@/lib/format";
import { labels } from "@/lib/labels";
import { firstName, monthYear, shortNames, sinceText, visitDay } from "@/lib/people";
import { salePill } from "@/lib/sale-status";
import { displayNumber } from "@/lib/units";
import { whatsappLink } from "@/lib/whatsapp";
import { cn } from "@/lib/utils";

const t = labels.peopleScreens.customer;
const methods = labels.peopleScreens.methods;
const ACTION = cn(
  "inline-flex min-h-bouton flex-[1_1_220px] items-center justify-center gap-2.5 rounded-bouton px-5 text-[17px] font-bold",
  "outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
);

/**
 * La fiche client, maquette v2 (écrans 14 et 14b) : qui il est, ce qu'il doit et depuis
 * quand, ce qu'il a acheté ce mois, sa dernière visite ; encaisser sa dette, lui vendre,
 * lui rappeler sa dette par WhatsApp ; puis ses achats et ses paiements. « Encaisser sa
 * dette » ouvre l'écran 18, la personne choisie (ADR 0073).
 */
export function CustomerDetailView({ customerId }: { customerId: string }) {
  const { timeZone, currency } = useCompanyLocale();
  const money = usePermission("debts:read");
  const canReadPayments = usePermission("payments:read");
  const [reminding, setReminding] = useState(false);
  const canPay = usePermission("payments:create");
  const sheet = useQuery({
    queryKey: queryKeys.people.sheet("customer", customerId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/analytics/customers/{customer_id}", {
          params: { path: { customer_id: customerId } },
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
        href="/customers"
        className="inline-flex min-h-11 items-center gap-2 self-start font-bold text-foreground hover:underline pointer-coarse:min-h-12"
      >
        <ArrowLeft className="size-[22px]" aria-hidden />
        {labels.people.back.customer}
      </Link>

      <PersonHeader
        name={data.name}
        rubrique="clients"
        subtitle={t.subtitle(data.phone, monthYear(data.created_at, timeZone))}
        phone={data.phone}
        editHref={`/customers/${customerId}/edit`}
        editPermission="customers:update"
      />

      <div className="grid grid-cols-[repeat(auto-fit,minmax(220px,1fr))] gap-3">
        {data.owed !== null && (
          <SheetTile
            rubrique="clients"
            label={t.owed}
            value={owes ? formatAmount(data.owed, currency) : t.owesNothing}
            detail={owes && data.owed_since ? sinceText(data.owed_since, timeZone) : null}
            detailInk="text-clients-encre"
          />
        )}
        <SheetTile
          rubrique="ventes"
          label={t.month}
          value={formatAmount(data.month_total, currency)}
          detail={t.visits(data.month_visits)}
        />
        <SheetTile
          rubrique="argent"
          label={t.last}
          value={data.last_visit_at ? visitDay(data.last_visit_at, timeZone) : t.never}
          detail={data.last_visit_at ? t.at(formatClock(data.last_visit_at, timeZone)) : null}
        />
      </div>

      <div className="flex flex-wrap gap-2.5">
        {money && owes && canPay && (
          <Link
            href={withFrom(`/finance/collect?customer=${customerId}`, `/customers/${customerId}`)}
            className={cn(ACTION, RUBRIQUE_CLASSES.clients.solid)}
          >
            {t.collect}
          </Link>
        )}
        <Link
          href={`/sales/new?customer=${customerId}`}
          className={cn(ACTION, RUBRIQUE_CLASSES.ventes.solid)}
        >
          {t.sell}
        </Link>
        {money && owes && (
          <button
            type="button"
            aria-expanded={reminding}
            className={cn(ACTION, "border-2 border-input bg-card text-foreground hover:bg-voile")}
            onClick={() => setReminding((on) => !on)}
          >
            <MessageCircle className="size-[22px]" aria-hidden />
            {t.remind}
          </button>
        )}
      </div>

      {reminding && data.owed && (
        <Reminder
          name={data.name}
          phone={data.phone}
          amount={formatAmount(data.owed, currency)}
          onClose={() => setReminding(false)}
        />
      )}

      <HistoryTabs
        rubrique="clients"
        label={t.tabs}
        tabs={[
          { id: "sales", label: t.sales, content: <Purchases customerId={customerId} /> },
          ...(canReadPayments
            ? [{ id: "payments", label: t.payments, content: <Payments customerId={customerId} /> }]
            : []),
        ]}
      />
    </div>
  );
}

/** Le rappel WhatsApp (écran 14b) : un message prêt, modifiable, puis `wa.me`. */
function Reminder({
  name,
  phone,
  amount,
  onClose,
}: {
  name: string;
  phone: string | null;
  amount: string;
  onClose: () => void;
}) {
  const me = useMe();
  const canReadShop = usePermission("company:read");
  const shop = useQuery({
    queryKey: ["companies", "me"],
    enabled: canReadShop,
    queryFn: () => unwrap(api.GET("/api/v1/companies/me")),
  });
  const ready = me.data && (!canReadShop || shop.data || shop.isError);
  const initial = ready
    ? t.reminder(
        firstName(name),
        firstName(me.data!.user.full_name),
        shop.data?.name ?? me.data!.company.name,
        amount,
        shop.data?.wave_number ?? null,
      )
    : null;
  const [edited, setEdited] = useState<string | null>(null);
  const text = edited ?? initial ?? "";

  return (
    <section className="flex flex-col gap-3 rounded-carte border-2 border-clients-anneau bg-card p-carte">
      <label htmlFor="reminder" className="text-[17px] font-bold">
        {t.message}
      </label>
      <textarea
        id="reminder"
        value={text}
        onChange={(event) => setEdited(event.target.value)}
        className="min-h-[120px] w-full resize-y rounded-champ border-2 border-input bg-card p-3.5 text-[17px] text-foreground outline-none focus-visible:border-clients focus-visible:outline-3 focus-visible:outline-clients-anneau"
      />
      <div className="flex flex-wrap gap-2.5">
        <a
          href={whatsappLink(text, phone)}
          target="_blank"
          rel="noreferrer"
          className={cn(ACTION, RUBRIQUE_CLASSES.ventes.solid)}
        >
          {t.openWhatsapp}
        </a>
        <button
          type="button"
          onClick={onClose}
          className={cn(
            ACTION,
            "flex-[0_1_160px] border-2 border-input bg-card text-foreground hover:bg-voile",
          )}
        >
          {t.close}
        </button>
      </div>
    </section>
  );
}

function Purchases({ customerId }: { customerId: string }) {
  const { timeZone, currency } = useCompanyLocale();
  const sales = useQuery({
    queryKey: queryKeys.people.history("customer", customerId, "sales"),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/analytics/customers/{customer_id}/sales", {
          params: { path: { customer_id: customerId } },
        }),
      ),
  });
  if (sales.isError) return <ErrorState error={sales.error} onRetry={() => void sales.refetch()} />;
  if (!sales.data) return <Skeleton className="h-40 w-full" />;
  if (sales.data.items.length === 0) {
    return <p className="border-t border-filet py-4 text-muted-foreground">{t.noSales}</p>;
  }
  return (
    <ul>
      {sales.data.items.map((sale) => {
        const pill = salePill(sale, currency);
        return (
          <li key={sale.sale_id}>
            <Link href={`/sales/${sale.sale_id}`} className={ROW}>
              <span className="min-w-0 flex-[1_1_220px]">
                <span className="block font-bold">
                  {t.saleLine(displayNumber(sale.sale_no), shortNames(sale.item_names))}
                </span>
                <span className="block text-muted-foreground">
                  {historyDay(sale.sold_at, timeZone)}
                </span>
              </span>
              <span className="text-lg font-extrabold numeric">
                {formatAmount(sale.total, currency)}
              </span>
              {pill && (
                <StatusPill
                  status={pill.status}
                  amount={pill.amount}
                  className="min-w-[130px] text-[15px]"
                />
              )}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

function Payments({ customerId }: { customerId: string }) {
  const { timeZone, currency } = useCompanyLocale();
  const payments = useQuery({
    queryKey: queryKeys.people.history("customer", customerId, "payments"),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/analytics/customers/{customer_id}/payments", {
          params: { path: { customer_id: customerId } },
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
      {payments.data.items.map((payment) => {
        const how = methods[payment.method] ?? "";
        const body = (
          <>
            <span className="min-w-0 flex-[1_1_220px]">
              <span className="block font-bold">
                {payment.on_debt ? t.collected(how) : t.paidAt(how)}
              </span>
              <span className="block text-muted-foreground">
                {historyDay(payment.paid_at, timeZone)}
              </span>
            </span>
            <span className="text-lg font-extrabold numeric">
              {formatAmount(payment.amount, currency)}
            </span>
            {payment.sale_no && (
              <span className="inline-flex min-w-[130px] items-center justify-center rounded-full bg-argent-teinte px-3 py-1.5 text-[15px] font-bold text-argent-encre">
                {t.saleNo(displayNumber(payment.sale_no))}
              </span>
            )}
          </>
        );
        return (
          <li key={payment.payment_id}>
            {payment.sale_id ? (
              <Link href={`/sales/${payment.sale_id}`} className={ROW}>
                {body}
              </Link>
            ) : (
              <div className={ROW}>{body}</div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

const ROW = cn(
  "flex flex-wrap items-center gap-x-3.5 gap-y-2.5 border-t border-filet py-3.5 text-foreground",
  "outline-none hover:bg-voile/60 focus-visible:ring-3 focus-visible:ring-ring/50",
);

/** « Aujourd'hui, 9 h 58 », « Jeudi 24 septembre » : le jour d'une ligne d'historique. */
function historyDay(value: string, timeZone: string): string {
  const day = visitDay(value, timeZone);
  return day === "Aujourd'hui" || day === "Hier" ? `${day}, ${formatClock(value, timeZone)}` : day;
}
