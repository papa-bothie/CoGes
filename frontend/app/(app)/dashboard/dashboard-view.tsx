"use client";

import { useQuery } from "@tanstack/react-query";
import { CreditCard, Plus, ShoppingCart, TriangleAlert, Users } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { OutboxLagBanner } from "@/components/dashboard/outbox-lag-banner";
import { ErrorState } from "@/components/error-state";
import { DayBars } from "@/components/kit/day-bars";
import { KitCard } from "@/components/kit/kit-card";
import { Avatar, ListRow } from "@/components/kit/list-row";
import { StatTile } from "@/components/kit/stat-tile";
import { StatusPill } from "@/components/kit/status-pill";
import { Skeleton } from "@/components/ui/skeleton";
import { useCompanyLocale, useMe } from "@/hooks/use-me";
import { withFrom } from "@/lib/back-target";
import { api, unwrap } from "@/lib/api/client";
import type { Schemas } from "@/lib/api/schema";
import { sumDecimals } from "@/lib/decimal";
import {
  formatAmount,
  formatClock,
  formatDayLong,
  formatFigure,
  formatQtyWithUnit,
  formatWeekdayShort,
} from "@/lib/format";
import { labels } from "@/lib/labels";
import { MAIN_NAV } from "@/lib/navigation";
import { can } from "@/lib/permissions";
import { salePill } from "@/lib/sale-status";
import { cn } from "@/lib/utils";

type Dashboard = Schemas["Dashboard"];
type Unit = keyof typeof labels.units;

const t = labels.dashboard;
const WEEK_DAYS = 7;
const PHONE_RECENT = 3;

/** Lien de chaque tuile : la rubrique où l'on agit (maquette 01). */
const TILE_LINKS = {
  sales: "/sales",
  cash: "/finance",
  receivables: withFrom("/finance/collect", "/dashboard"),
  stock: "/inventory",
} as const;

function firstName(fullName: string): string {
  return fullName.trim().split(/\s+/)[0] ?? fullName;
}

function quantity(value: string, unit: string): string {
  const known = unit in labels.units ? (unit as Unit) : null;
  return known
    ? formatQtyWithUnit(value, labels.units[known], labels.unitsPlural[known])
    : `${value} ${unit}`;
}

/**
 * Accueil de la maquette v2 (écran 01) ; sous 768 px, la version téléphone (écran 26) :
 * tuiles en 2 × 2, trois dernières ventes, sans graphique ni carte « À surveiller ».
 *
 * Chaque tuile ne s'affiche qu'à qui peut ouvrir la rubrique où elle mène : le vendeur voit
 * ses ventes, pas la caisse ni les dettes (le serveur reste juge de chaque lecture).
 */
export function DashboardView() {
  const { timeZone, currency } = useCompanyLocale();
  const me = useMe();
  const query = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => unwrap(api.GET("/api/v1/dashboard")),
  });
  const permissions = me.data?.permissions;
  const money = (value: string | undefined) => formatAmount(value, currency);

  if (query.isError) {
    return (
      <div className="mx-auto max-w-page">
        <h1 className="text-titre-page">{t.title}</h1>
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      </div>
    );
  }

  const data = query.data;
  const show = {
    cash: can(permissions, MAIN_NAV[4]?.permission),
    receivables: can(permissions, "debts:read"),
    stock: can(permissions, MAIN_NAV[2]?.permission),
    sell: can(permissions, "sales:create"),
  };

  const tiles =
    data &&
    [
      {
        key: "sales",
        rubrique: "ventes" as const,
        icon: ShoppingCart,
        label: t.revenueToday,
        short: t.revenueToday,
        value: money(data.revenue_today),
        detail: t.salesCount(data.sales_today),
        href: TILE_LINKS.sales,
        visible: true,
      },
      {
        key: "cash",
        rubrique: "argent" as const,
        icon: CreditCard,
        label: t.cash,
        short: t.cash,
        value: money(data.cash_on_hand),
        detail: t.cashHint,
        href: TILE_LINKS.cash,
        visible: show.cash,
      },
      {
        key: "receivables",
        rubrique: "clients" as const,
        icon: Users,
        label: t.receivables,
        short: t.receivablesShort,
        value: money(data.receivables_open),
        detail: t.receivablesHint(data.receivables_customer_count),
        href: TILE_LINKS.receivables,
        visible: show.receivables,
      },
      {
        key: "stock",
        rubrique: "stock" as const,
        icon: TriangleAlert,
        label: t.stockWatch,
        short: t.stockWatchShort,
        value: t.stockCount(data.stock_alert_count),
        detail: t.stockHint,
        href: TILE_LINKS.stock,
        visible: show.stock,
      },
    ].filter((tile) => tile.visible);

  return (
    <div className="mx-auto flex max-w-page flex-col gap-3.5 md:gap-6 md:pt-1">
      <OutboxLagBanner />

      <div className="flex flex-col gap-3.5 md:flex-row md:flex-wrap md:items-center md:justify-between md:gap-4">
        <div>
          <h1 className="text-2xl leading-tight font-extrabold tracking-[-0.01em] md:text-[32px] md:leading-[1.2]">
            {me.data ? t.greeting(firstName(me.data.user.full_name)) : t.title}
          </h1>
          <p className="text-muted-foreground md:mt-1 md:text-lg">
            {data ? formatDayLong(data.today) : " "}
          </p>
        </div>
        {show.sell && (
          <Link
            href="/sales/new"
            className={cn(
              "inline-flex min-h-16 items-center justify-center gap-2.5 rounded-tuile bg-ventes px-8 text-xl font-extrabold text-primary-foreground",
              "outline-none hover:bg-ventes/90 focus-visible:ring-3 focus-visible:ring-ring/50 md:font-bold",
            )}
          >
            <Plus className="size-7 md:size-[26px]" aria-hidden />
            {t.newSale}
          </Link>
        )}
      </div>

      {/* Ordinateur (01) : quatre grandes tuiles. */}
      <div className="hidden gap-4 md:grid md:grid-cols-[repeat(auto-fit,minmax(240px,1fr))]">
        {tiles
          ? tiles.map((tile) => (
              <StatTile
                key={tile.key}
                rubrique={tile.rubrique}
                icon={tile.icon}
                label={tile.label}
                value={tile.value}
                detail={tile.detail}
                href={tile.href}
              />
            ))
          : Array.from({ length: 4 }, (_, i) => (
              <Skeleton key={i} className="h-[170px] rounded-carte" />
            ))}
      </div>

      {/* Téléphone (26) : tuiles compactes en 2 × 2. */}
      <div className="grid grid-cols-2 gap-2.5 md:hidden">
        {tiles
          ? tiles.map((tile) => (
              <StatTile
                key={tile.key}
                compact
                rubrique={tile.rubrique}
                label={tile.short}
                value={tile.value}
                href={tile.href}
              />
            ))
          : Array.from({ length: 4 }, (_, i) => (
              <Skeleton key={i} className="h-20 rounded-tuile" />
            ))}
      </div>

      <div className="hidden flex-wrap items-stretch gap-4 md:flex">
        <WeekCard data={data} currency={currency} />
        <WatchCard data={data} currency={currency} />
      </div>

      <RecentSales data={data} currency={currency} timeZone={timeZone} />
    </div>
  );
}

function WeekCard({ data, currency }: { data: Dashboard | undefined; currency: string }) {
  const week = data?.revenue_trend.slice(-WEEK_DAYS) ?? [];
  const total = sumDecimals(week.map((point) => point.net_revenue));
  return (
    <section className="min-w-0 flex-[3_1_520px] rounded-carte border border-border bg-card p-carte">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-[21px] leading-7 font-bold">{t.week}</h2>
        <p className="text-muted-foreground">
          {t.weekTotal}{" "}
          <span className="font-bold numeric text-foreground">
            {data ? formatAmount(total, currency) : "—"}
          </span>
        </p>
      </div>
      {data ? (
        <DayBars
          className="mt-5"
          label={t.weekLabel}
          bars={week.map((point, index) => ({
            label: index === week.length - 1 ? t.today : formatWeekdayShort(point.day),
            display: formatFigure(point.net_revenue, currency),
            weight: Number(point.net_revenue),
            current: index === week.length - 1,
          }))}
        />
      ) : (
        <Skeleton className="mt-5 h-[280px] w-full" />
      )}
    </section>
  );
}

function WatchRow({
  href,
  tint,
  disc,
  initial,
  title,
  detail,
  ink,
}: {
  href: string;
  tint: string;
  disc: string;
  initial: string;
  title: string;
  detail: string;
  ink: string;
}) {
  return (
    <Link
      href={href}
      className={cn(
        "flex items-center gap-3 rounded-champ p-3.5 text-foreground outline-none",
        "focus-visible:ring-3 focus-visible:ring-ring/50",
        tint,
      )}
    >
      <span
        aria-hidden
        className={cn(
          "flex size-11 shrink-0 items-center justify-center rounded-full font-bold text-primary-foreground",
          disc,
        )}
      >
        {initial}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block font-bold">{title}</span>
        <span className={cn("block font-semibold", ink)}>{detail}</span>
      </span>
    </Link>
  );
}

function WatchCard({ data, currency }: { data: Dashboard | undefined; currency: string }) {
  const rows: ReactNode[] = [];
  for (const item of data?.watch_stock ?? []) {
    rows.push(
      <WatchRow
        key={item.product_id}
        href={`/products/${item.product_id}`}
        tint="bg-stock-teinte"
        disc="bg-stock"
        ink="text-stock-encre"
        initial={item.name.trim().charAt(0).toLocaleUpperCase("fr-FR")}
        title={item.name}
        detail={
          item.status === "out" ? t.watchOut : t.watchLeft(quantity(item.qty_on_hand, item.unit))
        }
      />,
    );
  }
  const debt = data?.watch_debt;
  if (debt) {
    rows.push(
      <WatchRow
        key={debt.customer_id}
        href={`/customers/${debt.customer_id}`}
        tint="bg-clients-teinte"
        disc="bg-clients"
        ink="text-clients-encre"
        initial={debt.customer_name
          .trim()
          .split(/\s+/)
          .slice(0, 2)
          .map((word) => word.charAt(0).toLocaleUpperCase("fr-FR"))
          .join("")}
        title={debt.customer_name}
        detail={t.watchDebt(formatAmount(debt.balance, currency), debt.days)}
      />,
    );
  }
  return (
    <section className="min-w-0 flex-[2_1_320px] rounded-carte border border-border bg-card p-carte">
      <h2 className="text-[21px] leading-7 font-bold">{t.watch}</h2>
      <div className="mt-3.5 flex flex-col gap-2.5">
        {!data ? (
          <Skeleton className="h-[220px] w-full rounded-champ" />
        ) : rows.length > 0 ? (
          rows
        ) : (
          <p className="text-muted-foreground">{t.nothingToWatch}</p>
        )}
      </div>
    </section>
  );
}

function RecentSales({
  data,
  currency,
  timeZone,
}: {
  data: Dashboard | undefined;
  currency: string;
  timeZone: string;
}) {
  const sales = data?.recent_sales ?? [];
  const name = (sale: Dashboard["recent_sales"][number]) =>
    sale.customer_name ?? t.anonymousCustomer;
  return (
    <>
      {/* Ordinateur (01). */}
      <KitCard
        className="hidden md:block"
        title={<span className="text-[21px] leading-7">{t.recentSales}</span>}
        action={
          <Link
            href="/sales"
            className="font-bold text-ventes underline underline-offset-2 hover:text-ventes-encre"
          >
            {t.seeAll}
          </Link>
        }
      >
        <div className="-mt-2">
          {!data ? (
            <Skeleton className="h-64 w-full" />
          ) : sales.length === 0 ? (
            <p className="border-t border-filet pt-4 text-muted-foreground">{t.noRecentSales}</p>
          ) : (
            sales.map((sale) => {
              const pill = salePill(sale, currency);
              return (
                <ListRow
                  key={sale.id}
                  href={`/sales/${sale.id}`}
                  leading={<Avatar name={sale.customer_name} />}
                  title={name(sale)}
                  subtitle={formatClock(sale.sold_at, timeZone)}
                  trailing={
                    <>
                      <span className="text-lg font-extrabold numeric">
                        {formatAmount(sale.total, currency)}
                      </span>
                      {pill && (
                        <StatusPill
                          status={pill.status}
                          amount={pill.amount}
                          className="min-w-[130px]"
                        />
                      )}
                    </>
                  }
                />
              );
            })
          )}
        </div>
      </KitCard>

      {/* Téléphone (26) : trois ventes, sans avatar, l'état en couleur sous le montant. */}
      <section className="rounded-[18px] border border-border bg-card px-3.5 py-1.5 md:hidden">
        <h2 className="py-2 font-bold">{t.recentSales}</h2>
        {!data ? (
          <Skeleton className="mb-2 h-40 w-full" />
        ) : sales.length === 0 ? (
          <p className="border-t border-filet py-3 text-muted-foreground">{t.noRecentSales}</p>
        ) : (
          sales.slice(0, PHONE_RECENT).map((sale) => {
            const pill = salePill(sale, currency);
            return (
              <Link
                key={sale.id}
                href={`/sales/${sale.id}`}
                className="flex min-h-12 items-center gap-2.5 border-t border-filet py-2.5 text-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-bold">{name(sale)}</span>
                  <span className="block text-sm text-muted-foreground">
                    {formatClock(sale.sold_at, timeZone)}
                  </span>
                </span>
                <span className="text-right">
                  <span className="block font-extrabold numeric">
                    {formatAmount(sale.total, currency)}
                  </span>
                  {pill && <PhoneStatus status={pill.status} amount={pill.amount} />}
                </span>
              </Link>
            );
          })
        )}
      </section>
    </>
  );
}

const PHONE_INK = {
  paid: "text-ventes-encre",
  remaining: "text-stock-encre",
  returned: "text-argent-encre",
  cancelled: "text-encre-2",
  writtenOff: "text-encre-2",
} as const;

function PhoneStatus({ status, amount }: { status: keyof typeof PHONE_INK; amount?: string }) {
  const text =
    status === "remaining"
      ? labels.kit.status.remaining(amount ?? "")
      : status === "returned"
        ? labels.kit.status.returned(amount ?? "")
        : labels.kit.status[status];
  return <span className={cn("block text-sm font-bold", PHONE_INK[status])}>{text}</span>;
}
