"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { Loader2, Plus, Search } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { ErrorState } from "@/components/error-state";
import { Chip } from "@/components/kit/chip";
import { fieldClasses, RUBRIQUE_CLASSES } from "@/components/kit/rubrique";
import { Skeleton } from "@/components/ui/skeleton";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { useCompanyLocale } from "@/hooks/use-me";
import { Can, usePermission } from "@/hooks/use-permission";
import { useTableParams } from "@/hooks/use-table-params";
import { api, unwrap } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { compareDecimal } from "@/lib/decimal";
import { formatAmount } from "@/lib/format";
import { labels } from "@/lib/labels";
import { agoText, dueDay, initials, sinceText } from "@/lib/people";
import { cn } from "@/lib/utils";

import { PERSON_RUBRIQUE, type PersonKind } from "./person-form";

type Row = Schemas["PersonRow"];

const t = labels.peopleScreens.list;
const PAGE_SIZE = 50;
const PATH = { customer: "/customers", supplier: "/suppliers" } as const;
const API = {
  customer: "/api/v1/analytics/customers",
  supplier: "/api/v1/analytics/suppliers",
} as const;

/**
 * Clients et fournisseurs, maquette v2 (écran 13) : le résumé de ce qui est dû, le choix
 * entre clients et fournisseurs (deux pages), la recherche par nom ou téléphone, « Tous »
 * ou ceux qui doivent, puis une carte par personne, ceux qui doivent d'abord. Sans le
 * droit de lire les dettes (un vendeur), aucun montant n'apparaît (ADR 0072).
 */
export function PeopleListView({ kind }: { kind: PersonKind }) {
  const table = useTableParams();
  const { currency, timeZone } = useCompanyLocale();
  const money = usePermission("debts:read");
  const rubrique = PERSON_RUBRIQUE[kind];
  const owing = money && table.get("filter") === "owing";
  const [text, setText] = useState(table.search);
  const term = useDebouncedValue(text.trim());
  const { setSearch } = table;
  useEffect(() => {
    if (term !== table.search) setSearch(term);
  }, [term, table.search, setSearch]);

  const filters = { owing: owing || undefined, search: table.search || undefined };
  const people = useInfiniteQuery({
    queryKey: queryKeys.people.list(kind, filters),
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET(API[kind], {
          params: { query: { ...filters, page: pageParam, page_size: PAGE_SIZE } },
        }),
      ),
    initialPageParam: 1,
    getNextPageParam: (last, pages) =>
      pages.reduce((count, page) => count + page.items.length, 0) < last.total
        ? last.page + 1
        : undefined,
  });

  const sentinel = useRef<HTMLDivElement>(null);
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = people;
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

  const first = people.data?.pages[0];
  const rows = people.data?.pages.flatMap((page) => page.items) ?? [];
  const summary = !first
    ? " "
    : first.owing_count === null || first.owed_total === null
      ? t.count[kind](kind === "customer" ? first.customer_count : first.supplier_count)
      : first.owing_count === 0
        ? kind === "customer"
          ? t.noCustomerOwes
          : t.noSupplierOwed
        : kind === "customer"
          ? t.customersOwe(first.owing_count, formatAmount(first.owed_total, currency))
          : t.weOweSuppliers(formatAmount(first.owed_total, currency), first.owing_count);

  return (
    <div className="mx-auto flex max-w-page flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-titre-page leading-[1.45] tracking-[-0.01em]">{t.title[kind]}</h1>
          <p className="text-lg text-muted-foreground">{summary}</p>
        </div>
        <Can permission={kind === "customer" ? "customers:create" : "suppliers:create"}>
          <Link
            href={`${PATH[kind]}/new`}
            className={cn(
              "inline-flex min-h-[60px] items-center gap-2.5 rounded-bouton px-[22px] text-[19px] font-bold",
              "outline-none hover:opacity-90 focus-visible:ring-3 focus-visible:ring-ring/50",
              RUBRIQUE_CLASSES[rubrique].solid,
            )}
          >
            <Plus className="size-6" aria-hidden />
            {t.add[kind]}
          </Link>
        </Can>
      </div>

      <nav aria-label={t.tabs} className="flex flex-wrap gap-3">
        {(["customer", "supplier"] as const).map((value) => {
          const current = value === kind;
          const count = first
            ? value === "customer"
              ? first.customer_count
              : first.supplier_count
            : null;
          return (
            <Link
              key={value}
              href={PATH[value]}
              aria-current={current ? "page" : undefined}
              className={cn(
                "flex min-h-16 flex-[1_1_200px] items-center justify-center rounded-bouton border-2 text-lg font-extrabold",
                "outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                current
                  ? RUBRIQUE_CLASSES[PERSON_RUBRIQUE[value]].picked
                  : "border-input bg-card text-encre-2 hover:bg-voile",
              )}
            >
              {count === null ? t.title[value] : t.tab[value](count)}
            </Link>
          );
        })}
      </nav>

      <div className="relative">
        <Search
          className="pointer-events-none absolute top-[17px] left-4 size-[22px] text-muted-foreground"
          aria-hidden
        />
        <label htmlFor="people-search" className="sr-only">
          {t.searchLabel}
        </label>
        <input
          id="people-search"
          type="search"
          autoComplete="off"
          placeholder={t.search}
          value={text}
          onChange={(event) => setText(event.target.value)}
          className={cn(fieldClasses(rubrique), "min-h-14 pr-4 pl-12 text-[17px] font-normal")}
        />
      </div>

      {money && (
        <div role="group" aria-label={t.filters} className="flex flex-wrap gap-2">
          {[
            { value: null, label: t.all },
            { value: "owing", label: t.owing[kind] },
          ].map((chip) => (
            <Chip
              key={chip.label}
              rubrique={rubrique}
              tone="plein"
              className="font-semibold"
              selected={(chip.value === "owing") === owing}
              onClick={() => table.setFilter("filter", chip.value)}
            >
              {chip.label}
            </Chip>
          ))}
        </div>
      )}

      {people.isError ? (
        <ErrorState error={people.error} onRetry={() => void people.refetch()} />
      ) : people.isPending ? (
        <Skeleton className="h-72 w-full rounded-carte" />
      ) : rows.length === 0 ? (
        <section className="rounded-carte border border-border bg-card px-5 py-10 text-center text-lg">
          <p className="font-bold">{t.empty}</p>
          <p className="mt-1 text-muted-foreground">{t.emptyHint}</p>
        </section>
      ) : (
        <ul className="grid grid-cols-[repeat(auto-fill,minmax(min(320px,100%),1fr))] gap-3">
          {rows.map((row) => (
            <li key={row.id}>
              <PersonCard row={row} kind={kind} currency={currency} timeZone={timeZone} />
            </li>
          ))}
        </ul>
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

/** Ce que dit la droite d'une carte : le montant dû et depuis quand, ou la dernière visite. */
function cardText(row: Row, kind: PersonKind, currency: string, timeZone: string) {
  const owes = row.owed !== null && compareDecimal(row.owed, "0") === 1;
  const amount =
    row.owed === null
      ? null
      : owes
        ? (kind === "customer" ? t.owes : t.weOwe)(formatAmount(row.owed, currency))
        : kind === "customer"
          ? t.owesNothing
          : t.nothingToPay;
  let sub: string;
  if (owes && kind === "customer" && row.owed_since) sub = sinceText(row.owed_since, timeZone);
  else if (owes && kind === "supplier")
    sub = row.due_date ? t.before(dueDay(row.due_date)) : t.noDueDate;
  else if (kind === "customer")
    sub = row.last_seen_at ? t.lastBuy(agoText(row.last_seen_at, timeZone)) : t.noBuy;
  else
    sub = row.last_seen_at ? t.lastDelivery(dueDay(row.last_seen_at.slice(0, 10))) : t.noDelivery;
  return { owes, amount, sub };
}

function PersonCard({
  row,
  kind,
  currency,
  timeZone,
}: {
  row: Row;
  kind: PersonKind;
  currency: string;
  timeZone: string;
}) {
  const rubrique = PERSON_RUBRIQUE[kind];
  const { owes, amount, sub } = cardText(row, kind, currency, timeZone);
  return (
    <Link
      href={`${PATH[kind]}/${row.id}`}
      className={cn(
        "flex min-h-[88px] flex-wrap items-center gap-x-3.5 gap-y-1 rounded-[20px] border border-border bg-card p-4 text-foreground",
        "outline-none hover:bg-voile focus-visible:ring-3 focus-visible:ring-ring/50",
      )}
    >
      <span
        aria-hidden
        className={cn(
          "flex size-[52px] shrink-0 items-center justify-center rounded-full text-lg font-extrabold",
          RUBRIQUE_CLASSES[rubrique].tint,
          RUBRIQUE_CLASSES[rubrique].ink,
        )}
      >
        {initials(row.name)}
      </span>
      <span className="min-w-[140px] flex-1">
        <span className="block text-[17px] font-bold break-words">{row.name}</span>
        {row.phone && <span className="block numeric text-muted-foreground">{row.phone}</span>}
      </span>
      <span className="ml-auto text-right">
        {amount && (
          <span
            className={cn(
              "block text-[17px] font-extrabold numeric",
              owes ? RUBRIQUE_CLASSES[rubrique].ink : "text-ventes-encre",
            )}
          >
            {amount}
          </span>
        )}
        <span className="block text-[15px] text-muted-foreground">{sub}</span>
      </span>
    </Link>
  );
}
