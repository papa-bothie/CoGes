"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Loader2, Menu, Plus, Search, SlidersVertical, Truck } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { ErrorState } from "@/components/error-state";
import { Chip } from "@/components/kit/chip";
import { ProductSquare } from "@/components/kit/list-row";
import { fieldClasses } from "@/components/kit/rubrique";
import { Skeleton } from "@/components/ui/skeleton";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { useCompanyLocale } from "@/hooks/use-me";
import { Can } from "@/hooks/use-permission";
import { useTableParams } from "@/hooks/use-table-params";
import { api, unwrap } from "@/lib/api/client";
import { useCategories } from "@/lib/api/queries/categories";
import { queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { formatAmount } from "@/lib/format";
import { labels } from "@/lib/labels";
import { qtyWithUnit } from "@/lib/units";
import { cn } from "@/lib/utils";

type StockLine = Schemas["StockLine"];

const t = labels.stockScreens.list;
const PAGE_SIZE = 50;

const STATUS_INK = {
  ok: "text-foreground",
  low: "text-stock-encre",
  out: "text-depenses-encre",
} as const;
const STATUS_BAR = { ok: "bg-ventes", low: "bg-barre-sortie", out: "bg-depenses" } as const;

/** Quantité affichée : « Épuisé », « Plus que 2 sacs », « 18 boîtes », rien si non suivi. */
function stockText(line: StockLine): string {
  if (!line.is_stock_tracked) return labels.products.notTracked;
  const qty = qtyWithUnit(line.qty_on_hand, line.unit);
  if (line.status === "out") return t.outText;
  return line.status === "low" ? t.left(qty) : qty;
}

/** Largeur de la barre : le niveau, au moins 6 % pour un article qui en a encore. */
function barPercent(line: StockLine): number {
  if (line.status === "out") return 0;
  return Math.max(6, Math.round(Number(line.level) * 100));
}

const SHORTCUT = cn(
  "flex min-h-20 items-center gap-3 rounded-carte border border-border bg-card px-5 text-libelle text-foreground",
  "outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50",
);

/**
 * L'écran Stock de la maquette v2 (07) : valeur du stock, raccourcis (livraison,
 * correction, rayons), recherche, puces d'état et de rayon, et la liste des articles,
 * épuisés d'abord, chacun avec sa quantité en couleur et sa barre de niveau. Filtre et
 * recherche restent dans l'URL ; le journal de tous les mouvements reste derrière un
 * lien (ADR 0071).
 */
export function ProductsListView() {
  const table = useTableParams();
  const { currency } = useCompanyLocale();
  const filter = table.get("filter") ?? "all";
  const [text, setText] = useState(table.search);
  const term = useDebouncedValue(text.trim());
  const { setSearch } = table;
  useEffect(() => {
    if (term !== table.search) setSearch(term);
  }, [term, table.search, setSearch]);

  const categories = useCategories();
  const summary = useQuery({
    queryKey: [...queryKeys.stock.all, "summary"],
    queryFn: () => unwrap(api.GET("/api/v1/inventory/stock/summary")),
  });
  const filters = {
    status: filter === "low" || filter === "out" ? (filter as "low" | "out") : undefined,
    category_id: filter !== "all" && filter !== "low" && filter !== "out" ? filter : undefined,
    search: table.search || undefined,
  };
  const stock = useInfiniteQuery({
    queryKey: queryKeys.stock.list({ infinite: true, ...filters }),
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/api/v1/inventory/stock", {
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
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = stock;
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

  const lines = stock.data?.pages.flatMap((page) => page.items) ?? [];
  const counts = summary.data;
  const [countText, prefix, value, suffix] = counts
    ? t.summary(t.count(counts.product_count), formatAmount(counts.stock_value, currency))
    : [];

  return (
    <div className="mx-auto flex max-w-page flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-titre-page leading-[1.45] tracking-[-0.01em]">{t.title}</h1>
          <p className="text-lg text-muted-foreground">
            {counts ? (
              <>
                {countText} {prefix}{" "}
                <span className="font-extrabold numeric text-stock-encre">{value}</span> {suffix}
              </>
            ) : (
              " "
            )}
          </p>
        </div>
        <Can permission="products:create">
          <Link
            href="/products/new"
            className={cn(
              "inline-flex min-h-[60px] items-center gap-2.5 rounded-bouton bg-stock px-[22px] text-[19px] font-bold text-primary-foreground",
              "outline-none hover:bg-stock/90 focus-visible:ring-3 focus-visible:ring-ring/50",
            )}
          >
            <Plus className="size-6" aria-hidden />
            {t.newArticle}
          </Link>
        </Can>
      </div>

      <Can permission="inventory:create">
        <div className="grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-3">
          <Link href="/inventory/receive" className={SHORTCUT}>
            <Truck className="size-[30px] text-stock" aria-hidden />
            {t.receive}
          </Link>
          <Link href="/inventory/adjust" className={SHORTCUT}>
            <SlidersVertical className="size-[30px] text-stock" aria-hidden />
            {t.adjust}
          </Link>
          <Link href="/products/categories" className={SHORTCUT}>
            <Menu className="size-[30px] text-stock" aria-hidden />
            {t.shelves}
          </Link>
        </div>
      </Can>

      <div className="relative">
        <Search
          className="pointer-events-none absolute top-[17px] left-4 size-[22px] text-muted-foreground"
          aria-hidden
        />
        <label htmlFor="stock-search" className="sr-only">
          {t.searchLabel}
        </label>
        <input
          id="stock-search"
          type="search"
          autoComplete="off"
          placeholder={t.search}
          value={text}
          onChange={(event) => setText(event.target.value)}
          className={cn(fieldClasses("stock"), "min-h-14 pr-4 pl-12 text-libelle font-normal")}
        />
      </div>

      <div role="group" aria-label={t.filters} className="flex flex-wrap gap-2">
        {[
          { value: "all", label: t.all },
          { value: "low", label: t.low(counts?.low_count ?? 0) },
          { value: "out", label: t.out(counts?.out_count ?? 0) },
          ...(categories.data ?? [])
            .filter((category) => category.parent_id === null)
            .map((category) => ({ value: category.id, label: category.name })),
        ].map((chip) => (
          <Chip
            key={chip.value}
            rubrique="stock"
            tone="plein"
            className="font-semibold"
            selected={filter === chip.value}
            onClick={() => table.setFilter("filter", chip.value === "all" ? null : chip.value)}
          >
            {chip.label}
          </Chip>
        ))}
      </div>

      {stock.isError ? (
        <ErrorState error={stock.error} onRetry={() => void stock.refetch()} />
      ) : stock.isPending ? (
        <Skeleton className="h-96 w-full rounded-carte" />
      ) : lines.length === 0 ? (
        <section className="rounded-carte border border-border bg-card px-5 py-10 text-center text-lg">
          <p className="font-bold">{t.empty}</p>
          <p className="mt-1 text-muted-foreground">{t.emptyHint}</p>
        </section>
      ) : (
        <section className="rounded-carte border border-border bg-card p-2.5">
          {lines.map((line) => (
            <Link
              key={line.product_id}
              href={`/products/${line.product_id}`}
              className={cn(
                "flex min-h-24 flex-wrap items-center gap-x-4 gap-y-3 rounded-[18px] px-3.5 py-3 text-foreground",
                "outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50",
              )}
            >
              <ProductSquare name={line.name} size="moyen" />
              <span className="min-w-0 flex-[1_1_220px]">
                <span className="block text-libelle">{line.name}</span>
                <span className="block text-muted-foreground">
                  {t.sold(line.category_name, formatAmount(line.unit_price, currency))}
                </span>
              </span>
              <span className="flex min-w-[150px] flex-col items-end gap-1.5">
                <span className={cn("text-[17px] font-extrabold", STATUS_INK[line.status])}>
                  {stockText(line)}
                </span>
                {line.is_stock_tracked && (
                  <span
                    role="img"
                    aria-label={t.level(line.name, barPercent(line))}
                    className="h-2.5 w-[140px] overflow-hidden rounded-full bg-filet"
                  >
                    <span
                      className={cn("block h-full rounded-full", STATUS_BAR[line.status])}
                      style={{ width: `${barPercent(line)}%` }}
                    />
                  </span>
                )}
              </span>
            </Link>
          ))}
        </section>
      )}
      <div ref={sentinel} aria-hidden className="h-px" />
      {isFetchingNextPage && (
        <p className="flex items-center justify-center gap-2 text-muted-foreground">
          <Loader2 className="size-4 animate-spin" aria-hidden />
          {labels.table.loading}
        </p>
      )}
      <Can permission="inventory:read">
        <Link
          href="/inventory"
          className="inline-flex min-h-12 items-center self-start font-bold text-stock-encre underline underline-offset-2 hover:text-foreground"
        >
          {t.journal}
        </Link>
      </Can>
    </div>
  );
}
