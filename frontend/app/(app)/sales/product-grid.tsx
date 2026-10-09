"use client";

import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useMemo, useState } from "react";

import { Chip } from "@/components/kit/chip";
import { ProductSquare } from "@/components/kit/list-row";
import { fieldClasses } from "@/components/kit/rubrique";
import { Skeleton } from "@/components/ui/skeleton";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { api, unwrap } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries/keys";
import { useStockFor, type StockLine } from "@/lib/api/queries/stock";
import type { Schemas } from "@/lib/api/schema";
import { formatAmount } from "@/lib/format";
import { labels } from "@/lib/labels";
import { qtyWithUnit } from "@/lib/units";
import { cn } from "@/lib/utils";

type Product = Schemas["ProductRead"];

const t = labels.sales.editor;
/** Une boutique tient dans une page : la grille montre jusqu'à 100 articles. */
const GRID_SIZE = 100;

/** « Plus que 2 sacs » sous le seuil, « Épuisé » à zéro, sinon « 18 boîtes en stock ». */
function stockText(line: StockLine | undefined): { text: string; low: boolean } | null {
  if (!line) return null;
  const qty = qtyWithUnit(line.qty_on_hand, line.unit);
  if (line.status === "out") return { text: t.out, low: true };
  if (line.status === "low") return { text: t.left(qty), low: true };
  return { text: t.inStock(qty), low: false };
}

/**
 * Côté gauche de « Nouvelle vente » (maquette 02) : recherche, puces de rayons et grille de
 * tuiles. Toucher une tuile ajoute 1 ; la pastille dit combien sont déjà dans le panier. Un
 * lecteur de code-barres tape le code puis Entrée : s'il ne reste qu'un article, il est
 * ajouté.
 */
export function ProductGrid({
  inCart,
  onAdd,
  disabled,
  currency,
}: {
  /** Quantité au panier par article, déjà formatée. */
  inCart: ReadonlyMap<string, string>;
  onAdd: (product: Product) => void;
  disabled: boolean;
  currency: string;
}) {
  const [text, setText] = useState("");
  const [categoryId, setCategoryId] = useState<string | null>(null);
  const term = useDebouncedValue(text.trim());

  const categories = useQuery({
    queryKey: queryKeys.categories.all,
    queryFn: () => unwrap(api.GET("/api/v1/categories", { params: { query: { page_size: 100 } } })),
  });
  const params = {
    search: term || undefined,
    category_id: categoryId ?? undefined,
    is_active: true,
    page_size: GRID_SIZE,
  };
  const products = useQuery({
    queryKey: queryKeys.products.list({ grid: true, ...params }),
    queryFn: () => unwrap(api.GET("/api/v1/products", { params: { query: params } })),
  });
  const items = useMemo(() => products.data?.items ?? [], [products.data]);
  const stock = useStockFor(useMemo(() => items.map((product) => product.id), [items]));

  return (
    <section className="flex min-w-0 flex-col gap-4">
      <h1 className="text-titre-page tracking-[-0.01em]">{labels.sales.newSale}</h1>
      <div className="relative">
        <Search
          className="pointer-events-none absolute top-[17px] left-4 size-[22px] text-muted-foreground"
          aria-hidden
        />
        <label htmlFor="article-search" className="sr-only">
          {t.searchLabel}
        </label>
        <input
          id="article-search"
          type="search"
          autoComplete="off"
          placeholder={t.search}
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key !== "Enter") return;
            event.preventDefault();
            const only = items.length === 1 ? items[0] : undefined;
            if (only && term === text.trim()) {
              onAdd(only);
              setText("");
            }
          }}
          className={cn(fieldClasses("ventes"), "min-h-14 pr-4 pl-12 text-libelle font-normal")}
        />
      </div>

      <div role="group" aria-label={t.categories} className="flex flex-wrap gap-2">
        <Chip selected={categoryId === null} onClick={() => setCategoryId(null)}>
          {t.all}
        </Chip>
        {categories.data?.items.map((category) => (
          <Chip
            key={category.id}
            selected={categoryId === category.id}
            onClick={() => setCategoryId(category.id)}
          >
            {category.name}
          </Chip>
        ))}
      </div>

      {products.isPending ? (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-3">
          {Array.from({ length: 8 }, (_, i) => (
            <Skeleton key={i} className="h-[150px] rounded-[18px]" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <p className="rounded-[18px] border-2 border-dashed border-input px-2 py-7 text-center text-libelle font-normal text-muted-foreground">
          {t.noProduct}
        </p>
      ) : (
        <ul className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-3">
          {items.map((product) => {
            const line = stock.data?.get(product.id);
            const status = stockText(line);
            const qty = inCart.get(product.id);
            const empty = product.is_stock_tracked && line?.status === "out";
            return (
              <li key={product.id} className="flex">
                <button
                  type="button"
                  aria-label={t.add(product.name)}
                  disabled={disabled || empty}
                  onClick={() => onAdd(product)}
                  className={cn(
                    "relative flex min-h-[150px] w-full flex-col items-start gap-2 rounded-[18px] border-2 border-border bg-card p-3.5 text-left text-foreground",
                    "outline-none hover:border-ventes focus-visible:ring-3 focus-visible:ring-ring/50",
                    "disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:border-border",
                  )}
                >
                  <ProductSquare name={product.name} size="grand" />
                  <span className="leading-tight font-bold">{product.name}</span>
                  <span className="text-lg font-extrabold numeric">
                    {formatAmount(product.unit_price, currency)}
                  </span>
                  {status && (
                    <span
                      className={cn(
                        "text-sm font-semibold",
                        status.low ? "text-stock-encre" : "text-muted-foreground",
                      )}
                    >
                      {status.text}
                    </span>
                  )}
                  {qty && (
                    <span className="absolute top-2.5 right-2.5 flex h-8 min-w-8 items-center justify-center rounded-full bg-ventes px-1.5 font-extrabold numeric text-primary-foreground">
                      {qty}
                    </span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
