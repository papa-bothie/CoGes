"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Undo2, X } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { DataTable, type Column } from "@/components/data-table";
import { ErrorState } from "@/components/error-state";
import { FieldError } from "@/components/field-error";
import { Money } from "@/components/money";
import { SearchCombobox } from "@/components/search-combobox";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useCompanyLocale } from "@/hooks/use-me";
import { usePermission } from "@/hooks/use-permission";
import { useTableParams } from "@/hooks/use-table-params";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/queries/keys";
import { useStockFor } from "@/lib/api/queries/stock";
import type { Schemas } from "@/lib/api/schema";
import { compareDecimal } from "@/lib/decimal";
import { formatDateTime, formatQty } from "@/lib/format";
import { dayEndIso, dayStartIso } from "@/lib/format/zoned";
import { labels } from "@/lib/labels";
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
const ALL = "all";
/** Seuls les mouvements saisis à la main se corrigent depuis le stock (ADR 0017, complément). */
const MANUAL = new Set<MovementType>([
  "initial",
  "purchase_in",
  "supplier_return_out",
  "adjustment",
  "loss",
]);

async function searchProducts(text: string): Promise<Product[]> {
  const page = await unwrap(
    api.GET("/api/v1/products", { params: { query: { search: text || undefined, page_size: 8 } } }),
  );
  return page.items;
}

/** Journal append-only : on le lit, on le filtre, on le corrige par un mouvement inverse. */
export function MovementJournal() {
  const table = useTableParams();
  const { timeZone, currency } = useCompanyLocale();
  const canCorrect = usePermission("inventory:update");
  const [toReverse, setToReverse] = useState<Movement | null>(null);

  const productId = table.get("product");
  const type = table.get("type") as MovementType | null;
  const from = table.get("from") ?? "";
  const to = table.get("to") ?? "";

  const params = {
    page: table.page,
    page_size: table.pageSize,
    product_id: productId ?? undefined,
    type: type ?? undefined,
    date_from: (from && dayStartIso(from, timeZone)) || undefined,
    date_to: (to && dayEndIso(to, timeZone)) || undefined,
  };
  const query = useQuery({
    queryKey: queryKeys.movements.list(params),
    queryFn: () => unwrap(api.GET("/api/v1/inventory/movements", { params: { query: params } })),
    placeholderData: keepPreviousData,
  });
  const movements = useMemo(() => query.data?.items ?? [], [query.data]);

  // Libellés des articles : tout article qui a un mouvement a une ligne de stock.
  const productIds = useMemo(() => {
    const ids = new Set(movements.map((movement) => movement.product_id));
    if (productId) ids.add(productId);
    return [...ids];
  }, [movements, productId]);
  const names = useStockFor(productIds);
  // Mouvements déjà annulés **sur cette page** ; au-delà, le serveur refuse (`already_reversed`).
  const reversed = new Set(movements.map((movement) => movement.reversal_of_movement_id));

  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;

  const filteredProduct = productId ? names.data?.get(productId) : undefined;

  const columns: Column<Movement>[] = [
    {
      id: "date",
      header: labels.stock.journal.date,
      cell: (movement) => (
        <span className="numeric whitespace-nowrap">
          {formatDateTime(movement.occurred_at, timeZone)}
        </span>
      ),
    },
    {
      id: "product",
      header: labels.stock.journal.product,
      cell: (movement) => {
        const line = names.data?.get(movement.product_id);
        return line ? (
          <div>
            <p className="font-medium">{line.name}</p>
            <p className="text-xs numeric text-muted-foreground">{line.sku}</p>
          </div>
        ) : (
          <span className="text-muted-foreground">—</span>
        );
      },
    },
    {
      id: "type",
      header: labels.stock.journal.type,
      cell: (movement) => (
        <span className="flex flex-wrap items-center gap-1.5">
          {labels.stock.movementTypes[movement.type]}
          {movement.reversal_of_movement_id && (
            <Badge variant="neutral">{labels.stock.journal.reversal}</Badge>
          )}
          {reversed.has(movement.id) && (
            <Badge variant="neutral">{labels.stock.journal.reversed}</Badge>
          )}
        </span>
      ),
    },
    {
      id: "qty",
      header: labels.stock.journal.qty,
      numeric: true,
      cell: (movement) => {
        const positive = compareDecimal(movement.qty_delta, "0") === 1;
        return (
          <span className={cn("font-medium", positive ? "text-success-ink" : "text-danger-ink")}>
            {positive ? "+" : ""}
            {formatQty(movement.qty_delta)}
          </span>
        );
      },
    },
    {
      id: "cost",
      header: labels.stock.journal.unitCost,
      numeric: true,
      cell: (movement) => <Money value={movement.unit_cost} currency={currency} />,
    },
    {
      id: "note",
      header: labels.stock.journal.note,
      className: "max-w-64",
      cell: (movement) => (
        <span className="line-clamp-2 text-sm text-muted-foreground">{movement.note ?? "—"}</span>
      ),
    },
    {
      id: "actions",
      header: "",
      className: "w-28 text-right",
      cell: (movement) =>
        canCorrect &&
        MANUAL.has(movement.type) &&
        !movement.reversal_of_movement_id &&
        !reversed.has(movement.id) ? (
          <Button variant="ghost" size="sm" onClick={() => setToReverse(movement)}>
            <Undo2 aria-hidden />
            {labels.stock.journal.correct}
          </Button>
        ) : null,
    },
  ];

  return (
    <>
      <DataTable
        caption={labels.stock.tabs.journal}
        columns={columns}
        rows={query.data?.items}
        rowKey={(movement) => movement.id}
        total={query.data?.total ?? 0}
        page={table.page}
        pageSize={table.pageSize}
        onPageChange={table.setPage}
        loading={query.isFetching}
        empty={labels.stock.journal.empty}
        filters={
          <>
            {productId ? (
              <span className="flex h-9 items-center gap-1 rounded-lg border bg-card pr-1 pl-3 text-sm">
                {filteredProduct?.name ?? "…"}
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={labels.stock.journal.clearProduct}
                  onClick={() => table.setFilter("product", null)}
                >
                  <X />
                </Button>
              </span>
            ) : (
              <SearchCombobox
                className="w-72"
                label={labels.stock.journal.productFilter}
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
            <Select
              value={type ?? ALL}
              onValueChange={(value) => table.setFilter("type", value === ALL ? null : value)}
            >
              <SelectTrigger className="w-48" aria-label={labels.stock.journal.typeFilter}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>{labels.stock.journal.allTypes}</SelectItem>
                {TYPES.map((value) => (
                  <SelectItem key={value} value={value}>
                    {labels.stock.movementTypes[value]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <label className="flex items-center gap-2 text-sm text-muted-foreground">
              {labels.sales.dateFrom}
              <Input
                type="date"
                value={from}
                max={to || undefined}
                onChange={(event) => table.setFilter("from", event.target.value || null)}
                className="h-9 w-40"
              />
            </label>
            <label className="flex items-center gap-2 text-sm text-muted-foreground">
              {labels.sales.dateTo}
              <Input
                type="date"
                value={to}
                min={from || undefined}
                onChange={(event) => table.setFilter("to", event.target.value || null)}
                className="h-9 w-40"
              />
            </label>
          </>
        }
      />
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
