"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Loader2, Plus, Search } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { ErrorState } from "@/components/error-state";
import { Chip } from "@/components/kit/chip";
import { Avatar } from "@/components/kit/list-row";
import { fieldClasses } from "@/components/kit/rubrique";
import { StatusPill } from "@/components/kit/status-pill";
import { Skeleton } from "@/components/ui/skeleton";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { useCompanyLocale } from "@/hooks/use-me";
import { Can } from "@/hooks/use-permission";
import { useTableParams } from "@/hooks/use-table-params";
import { api, unwrap } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { formatAmount, formatClock, formatDayLong } from "@/lib/format";
import { dayEndIso, dayStartIso } from "@/lib/format/zoned";
import { labels } from "@/lib/labels";
import { addDays, todayIn } from "@/lib/period";
import { salePill } from "@/lib/sale-status";
import { isSalesPeriod, SALES_PERIODS, salesPeriodDays } from "@/lib/sales-period";
import { displayNumber } from "@/lib/units";
import { cn } from "@/lib/utils";

type Sale = Schemas["SaleRead"];
type SaleState = Schemas["SalePaymentState"];
type DayTotal = Schemas["SaleDayTotal"];

const t = labels.sales.list;
const STATES = ["all", "paid", "unpaid", "returned", "cancelled"] as const;
const PAGE_SIZE = 50;

function isState(value: string | null): value is (typeof STATES)[number] {
  return value !== null && (STATES as readonly string[]).includes(value);
}

/** « 5 ventes · 88 200 F » : le nombre compte les annulées, le total non (maquette 03). */
function DayHeading({
  day,
  today,
  totals,
  currency,
}: {
  day: string;
  today: string;
  totals: DayTotal | undefined;
  currency: string;
}) {
  const title =
    day === today
      ? t.today
      : day === addDays(today, -1)
        ? t.yesterday(formatDayLong(day).toLocaleLowerCase("fr-FR"))
        : formatDayLong(day);
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-2 px-4 pt-2 pb-1">
      <h2 className="text-[19px] leading-7 font-bold">{title}</h2>
      {totals && (
        <span className="text-muted-foreground">
          {labels.sales.count(totals.sale_count)} ·{" "}
          <span className="font-extrabold numeric text-foreground">
            {formatAmount(totals.total, currency)}
          </span>
        </span>
      )}
    </div>
  );
}

function SaleRow({ sale, timeZone, currency }: { sale: Sale; timeZone: string; currency: string }) {
  const pill = salePill(sale, currency);
  const cancelled = sale.status === "cancelled";
  return (
    <Link
      href={`/sales/${sale.id}`}
      className={cn(
        "flex min-h-[100px] flex-wrap items-center gap-x-4 gap-y-3 rounded-[18px] px-4 py-3.5 text-foreground",
        "outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50",
        cancelled && "opacity-60",
      )}
    >
      <Avatar name={sale.customer_name} rubrique="clients" size="moyen" />
      <span className="min-w-0 flex-[1_1_200px]">
        <span className="block text-libelle">{sale.customer_name ?? labels.sales.anonymous}</span>
        <span className="block text-muted-foreground">
          {t.line(
            displayNumber(sale.sale_no),
            formatClock(sale.sold_at, timeZone),
            sale.item_count,
          )}
        </span>
      </span>
      <span className={cn("text-[19px] font-extrabold numeric", cancelled && "line-through")}>
        {formatAmount(sale.total, currency)}
      </span>
      {pill && <StatusPill status={pill.status} amount={pill.amount} className="min-w-[140px]" />}
    </Link>
  );
}

/**
 * Liste des ventes de la maquette v2 (écran 03) : résumé du jour, recherche par nom ou
 * numéro, puces de période et d'état, ventes groupées par jour avec leur total. Les
 * brouillons n'y sont pas : « Nouvelle vente » les reprend (ADR 0070). Période, état et
 * recherche restent dans l'URL.
 */
export function SalesListView() {
  const table = useTableParams();
  const { timeZone, currency } = useCompanyLocale();
  const today = todayIn(timeZone);
  const period = isSalesPeriod(table.get("period")) ? table.get("period")! : "week";
  const stateParam = table.get("state");
  const state = isState(stateParam) ? stateParam : "all";
  const [text, setText] = useState(table.search);
  const term = useDebouncedValue(text.trim());
  const { setSearch } = table;
  useEffect(() => {
    if (term !== table.search) setSearch(term);
  }, [term, table.search, setSearch]);

  const days = salesPeriodDays(isSalesPeriod(period) ? period : "week", today);
  const filters = {
    date_from: dayStartIso(days.from, timeZone) ?? "",
    date_to: dayEndIso(days.to, timeZone) ?? "",
    state: state === "all" ? undefined : (state as SaleState),
    search: table.search || undefined,
  };

  const sales = useInfiniteQuery({
    queryKey: queryKeys.sales.list({ infinite: true, ...filters }),
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/api/v1/sales", {
          params: {
            query: { ...filters, include_drafts: false, page: pageParam, page_size: PAGE_SIZE },
          },
        }),
      ),
    initialPageParam: 1,
    getNextPageParam: (last, pages) =>
      pages.reduce((count, page) => count + page.items.length, 0) < last.total
        ? last.page + 1
        : undefined,
  });
  const totals = useQuery({
    queryKey: queryKeys.sales.list({ dayTotals: true, ...filters }),
    queryFn: () => unwrap(api.GET("/api/v1/sales/day-totals", { params: { query: filters } })),
  });
  const todayParams = {
    date_from: dayStartIso(today, timeZone) ?? "",
    date_to: dayEndIso(today, timeZone) ?? "",
  };
  const summary = useQuery({
    queryKey: queryKeys.sales.list({ dayTotals: true, ...todayParams }),
    queryFn: () => unwrap(api.GET("/api/v1/sales/day-totals", { params: { query: todayParams } })),
  });

  // Les ventes suivantes arrivent quand le bas de la liste devient visible.
  const sentinel = useRef<HTMLDivElement>(null);
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = sales;
  useEffect(() => {
    const target = sentinel.current;
    if (!target || !hasNextPage || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting) && !isFetchingNextPage) {
          void fetchNextPage();
        }
      },
      { rootMargin: "256px" },
    );
    observer.observe(target);
    return () => observer.disconnect();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  const rows = sales.data?.pages.flatMap((page) => page.items) ?? [];
  const groups: { day: string; sales: Sale[] }[] = [];
  for (const sale of rows) {
    const day = todayIn(timeZone, new Date(sale.sold_at));
    const last = groups.at(-1);
    if (last?.day === day) last.sales.push(sale);
    else groups.push({ day, sales: [sale] });
  }
  const totalsByDay = new Map(totals.data?.items.map((item) => [item.day, item]));
  const todayTotals = summary.data?.items[0];

  return (
    <div className="mx-auto flex max-w-page flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-titre-page tracking-[-0.01em]">{t.title}</h1>
          <p className="mt-0.5 text-lg text-muted-foreground">
            {summary.data
              ? t.summary(
                  labels.sales.count(todayTotals?.confirmed_count ?? 0),
                  formatAmount(todayTotals?.total ?? "0", currency),
                )
              : " "}
          </p>
        </div>
        <Can permission="sales:create">
          <Link
            href="/sales/new"
            className={cn(
              "inline-flex min-h-[60px] items-center gap-2.5 rounded-bouton bg-ventes px-[22px] text-[19px] font-bold text-primary-foreground",
              "outline-none hover:bg-ventes/90 focus-visible:ring-3 focus-visible:ring-ring/50",
            )}
          >
            <Plus className="size-6" aria-hidden />
            {labels.sales.newSale}
          </Link>
        </Can>
      </div>

      <div className="relative">
        <Search
          className="pointer-events-none absolute top-[17px] left-4 size-[22px] text-muted-foreground"
          aria-hidden
        />
        <label htmlFor="sale-search" className="sr-only">
          {t.searchLabel}
        </label>
        <input
          id="sale-search"
          type="search"
          autoComplete="off"
          placeholder={t.search}
          value={text}
          onChange={(event) => setText(event.target.value)}
          className={cn(fieldClasses("ventes"), "min-h-14 pr-4 pl-12 text-libelle font-normal")}
        />
      </div>

      <div className="flex flex-wrap gap-2">
        <div role="group" aria-label={t.periodsLabel} className="contents">
          {SALES_PERIODS.map((value) => (
            <Chip
              key={value}
              tone="plein"
              className="font-semibold"
              selected={period === value}
              onClick={() => table.setFilter("period", value === "week" ? null : value)}
            >
              {t.periods[value]}
            </Chip>
          ))}
        </div>
        <span aria-hidden className="mx-1.5 my-1 w-px bg-input" />
        <div role="group" aria-label={t.statesLabel} className="contents">
          {STATES.map((value) => (
            <Chip
              key={value}
              tone="plein"
              className="font-semibold"
              selected={state === value}
              onClick={() => table.setFilter("state", value === "all" ? null : value)}
            >
              {t.states[value]}
            </Chip>
          ))}
        </div>
      </div>

      {sales.isError ? (
        <ErrorState error={sales.error} onRetry={() => void sales.refetch()} />
      ) : sales.isPending ? (
        <Skeleton className="h-96 w-full rounded-carte" />
      ) : groups.length === 0 ? (
        <section className="rounded-carte border border-border bg-card px-5 py-10 text-center text-lg">
          <p className="font-bold">{t.empty}</p>
          <p className="mt-1 text-muted-foreground">{t.emptyHint}</p>
        </section>
      ) : (
        groups.map((group) => (
          <section
            key={group.day}
            className="rounded-carte border border-border bg-card p-3 text-card-foreground"
          >
            <DayHeading
              day={group.day}
              today={today}
              totals={totalsByDay.get(group.day)}
              currency={currency}
            />
            {group.sales.map((sale) => (
              <SaleRow key={sale.id} sale={sale} timeZone={timeZone} currency={currency} />
            ))}
          </section>
        ))
      )}
      <div ref={sentinel} aria-hidden className="h-px" />
      {isFetchingNextPage && (
        <p className="flex items-center justify-center gap-2 text-muted-foreground">
          <Loader2 className="size-4 animate-spin" aria-hidden />
          {labels.table.loading}
        </p>
      )}
    </div>
  );
}
