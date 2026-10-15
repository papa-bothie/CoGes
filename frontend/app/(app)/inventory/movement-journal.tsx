"use client";

import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Undo2, X } from "lucide-react";
import { useId, useMemo, useState } from "react";
import { toast } from "sonner";

import { ErrorState } from "@/components/error-state";
import { FieldError } from "@/components/field-error";
import { FilterChips, MoreButton, OUTLINE_ACTION } from "@/components/kit/filter-chips";
import { ListRow, ProductSquare } from "@/components/kit/list-row";
import { fieldClasses } from "@/components/kit/rubrique";
import { SearchCombobox } from "@/components/search-combobox";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { useCompanyLocale } from "@/hooks/use-me";
import { usePermission } from "@/hooks/use-permission";
import { useTableParams } from "@/hooks/use-table-params";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/queries/keys";
import { useStockFor } from "@/lib/api/queries/stock";
import type { Schemas } from "@/lib/api/schema";
import { compareDecimal } from "@/lib/decimal";
import { formatAmount, formatDateTime, formatQty } from "@/lib/format";
import { dayEndIso, dayStartIso } from "@/lib/format/zoned";
import { labels } from "@/lib/labels";
import { MINUS } from "@/lib/money";
import { cn } from "@/lib/utils";

type Movement = Schemas["MovementRead"];
type MovementType = Schemas["MovementType"];
type Product = Schemas["ProductRead"];

const TYPES: readonly MovementType[] = [
  "initial",
  "purchase_in",
  "sale_out",
  "customer_return_in",
  "supplier_return_out",
  "adjustment",
  "loss",
];
/** Seuls les mouvements saisis à la main se corrigent depuis le stock (ADR 0017, complément). */
const MANUAL = new Set<MovementType>([
  "initial",
  "purchase_in",
  "supplier_return_out",
  "adjustment",
  "loss",
]);
const j = labels.stock.journal;

async function searchProducts(text: string): Promise<Product[]> {
  const page = await unwrap(
    api.GET("/api/v1/products", { params: { query: { search: text || undefined, page_size: 8 } } }),
  );
  return page.items;
}

/**
 * Journal append-only, dans le style de la maquette v2 : l'article, le type en puces, les
 * dates ; une ligne par mouvement, quantité en vert ou en orange, et « Corriger » qui ajoute
 * le mouvement inverse (ADR 0017).
 */
export function MovementJournal() {
  const table = useTableParams();
  const id = useId();
  const { timeZone, currency } = useCompanyLocale();
  const canCorrect = usePermission("inventory:update");
  const [toReverse, setToReverse] = useState<Movement | null>(null);

  const productId = table.get("product");
  const type = table.get("type") as MovementType | null;
  const from = table.get("from") ?? "";
  const to = table.get("to") ?? "";

  const filters = {
    page_size: table.pageSize,
    product_id: productId ?? undefined,
    type: type ?? undefined,
    date_from: (from && dayStartIso(from, timeZone)) || undefined,
    date_to: (to && dayEndIso(to, timeZone)) || undefined,
  };
  const query = useInfiniteQuery({
    queryKey: queryKeys.movements.list({ ...filters, infinite: true }),
    initialPageParam: 1,
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/api/v1/inventory/movements", {
          params: { query: { ...filters, page: pageParam } },
        }),
      ),
    getNextPageParam: (last) =>
      last.page * last.page_size < last.total ? last.page + 1 : undefined,
  });
  const movements = useMemo(
    () => query.data?.pages.flatMap((page) => page.items) ?? [],
    [query.data],
  );
  const total = query.data?.pages[0]?.total;

  // Libellés des articles : tout article qui a un mouvement a une ligne de stock.
  const productIds = useMemo(() => {
    const ids = new Set(movements.map((movement) => movement.product_id));
    if (productId) ids.add(productId);
    return [...ids];
  }, [movements, productId]);
  const names = useStockFor(productIds);
  // Mouvements déjà annulés **parmi ceux chargés** ; au-delà, le serveur refuse (`already_reversed`).
  const reversed = new Set(movements.map((movement) => movement.reversal_of_movement_id));
  const filteredProduct = productId ? names.data?.get(productId) : undefined;
  const dateField = cn(fieldClasses("stock"), "min-h-cible px-3 numeric");

  return (
    <>
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          {productId ? (
            <span className="inline-flex min-h-cible items-center gap-1 rounded-full border-2 border-stock bg-stock-teinte pr-1 pl-4 font-bold text-stock-encre">
              {filteredProduct?.name ?? "…"}
              <Button
                variant="ghost"
                size="icon"
                aria-label={j.clearProduct}
                onClick={() => table.setFilter("product", null)}
              >
                <X />
              </Button>
            </span>
          ) : (
            <SearchCombobox
              className="w-72"
              label={j.productFilter}
              queryKey={[...queryKeys.products.search, "journal"]}
              search={searchProducts}
              itemKey={(item) => item.id}
              onSelect={(item) => table.setFilter("product", item.id)}
              renderItem={(item) => (
                <span className="flex justify-between gap-3">
                  <span>{item.name}</span>
                  <span className="numeric text-muted-foreground">{item.sku}</span>
                </span>
              )}
            />
          )}
          <label htmlFor={`${id}-from`} className="ml-2 font-bold">
            {labels.sales.dateFrom}
          </label>
          <input
            id={`${id}-from`}
            type="date"
            value={from}
            max={to || undefined}
            onChange={(event) => table.setFilter("from", event.target.value || null)}
            className={cn(dateField, "w-44")}
          />
          <label htmlFor={`${id}-to`} className="font-bold">
            {labels.sales.dateTo}
          </label>
          <input
            id={`${id}-to`}
            type="date"
            value={to}
            min={from || undefined}
            onChange={(event) => table.setFilter("to", event.target.value || null)}
            className={cn(dateField, "w-44")}
          />
        </div>
        <FilterChips
          label={j.typeFilter}
          value={type}
          allLabel={j.allTypes}
          options={TYPES.map((value) => [value, labels.stock.movementTypes[value]] as const)}
          onChange={(next) => table.setFilter("type", next)}
        />
        <p className="text-muted-foreground">
          {total !== undefined ? labels.table.total(total) : null}
        </p>
      </div>

      <section className="rounded-carte border border-border bg-card px-carte pb-2">
        {query.isError ? (
          <div className="py-carte">
            <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          </div>
        ) : !query.data ? (
          <Skeleton className="my-carte h-64 w-full rounded-champ" />
        ) : movements.length === 0 ? (
          <p className="py-carte text-muted-foreground">{j.empty}</p>
        ) : (
          <ul aria-label={labels.stock.tabs.journal} className="[&>li:first-child>*]:border-t-0">
            {movements.map((movement) => {
              const line = names.data?.get(movement.product_id);
              const positive = compareDecimal(movement.qty_delta, "0") === 1;
              const why = movement.reason_code
                ? labels.stock.reasons[movement.reason_code]
                : movement.note;
              const canReverse =
                canCorrect &&
                MANUAL.has(movement.type) &&
                !movement.reversal_of_movement_id &&
                !reversed.has(movement.id);
              return (
                <li key={movement.id}>
                  <ListRow
                    wrap
                    className="flex-wrap"
                    leading={<ProductSquare name={line?.name ?? "?"} size="petit" />}
                    title={line?.name ?? "—"}
                    subtitle={
                      <>
                        {labels.stock.movementTypes[movement.type]}
                        {movement.reversal_of_movement_id && ` · ${j.reversal}`}
                        {reversed.has(movement.id) && ` · ${j.reversed}`}
                        {" · "}
                        <span className="numeric">
                          {formatDateTime(movement.occurred_at, timeZone)}
                        </span>
                        {why ? ` · ${why}` : ""}
                        {" · "}
                        {j.unitCost.toLowerCase()}{" "}
                        <span className="numeric">
                          {formatAmount(movement.unit_cost, currency)}
                        </span>
                      </>
                    }
                    trailing={
                      <>
                        <span
                          className={cn(
                            "text-lg font-extrabold numeric",
                            positive ? "text-ventes-encre" : "text-depenses-encre",
                          )}
                        >
                          {positive ? "+" : MINUS}
                          {formatQty(movement.qty_delta.replace(/^-/, ""))}
                        </span>
                        {canReverse && (
                          <button
                            type="button"
                            className={OUTLINE_ACTION}
                            onClick={() => setToReverse(movement)}
                          >
                            <Undo2 className="size-5" aria-hidden />
                            {j.correct}
                          </button>
                        )}
                      </>
                    }
                  />
                </li>
              );
            })}
          </ul>
        )}
      </section>
      {query.hasNextPage && (
        <MoreButton pending={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()} />
      )}
      <ReverseDialog movement={toReverse} onClose={() => setToReverse(null)} />
    </>
  );
}

function ReverseDialog({ movement, onClose }: { movement: Movement | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const reverse = useMutation({
    meta: { toastError: false },
    mutationFn: (id: string) =>
      unwrap(
        api.POST("/api/v1/inventory/movements/{movement_id}/reverse", {
          params: { path: { movement_id: id } },
        }),
      ),
    onSuccess: () => {
      for (const key of [queryKeys.stock.all, queryKeys.movements.all, queryKeys.dashboard]) {
        void queryClient.invalidateQueries({ queryKey: key });
      }
      toast.success(labels.stock.journal.corrected);
      onClose();
    },
    onError: (failure) => setError(errorMessage(failure)),
  });

  return (
    <Dialog
      open={movement !== null}
      onOpenChange={(open) => {
        if (!open) {
          setError(null);
          onClose();
        }
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{labels.stock.journal.correctTitle}</DialogTitle>
          <DialogDescription>{labels.stock.journal.correctDescription}</DialogDescription>
        </DialogHeader>
        {movement && (
          <p className="text-sm">
            {labels.stock.movementTypes[movement.type]} ·{" "}
            <span className="font-medium numeric">{formatQty(movement.qty_delta)}</span>
          </p>
        )}
        <FieldError message={error} />
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {labels.common.close}
          </Button>
          <Button
            disabled={reverse.isPending || !movement}
            onClick={() => movement && reverse.mutate(movement.id)}
          >
            {labels.stock.journal.correctSubmit}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
