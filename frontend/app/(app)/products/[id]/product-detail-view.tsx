"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Boxes, Pencil, Tag } from "lucide-react";
import Link from "next/link";
import { useMemo, useState, type ReactNode } from "react";
import { toast } from "sonner";

import { ErrorState } from "@/components/error-state";
import { FieldError } from "@/components/field-error";
import { MovementDialog } from "@/components/inventory/movement-dialog";
import { Money } from "@/components/money";
import { PageHeader } from "@/components/page-header";
import { StockStatusBadge } from "@/components/status/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { useCompanyLocale } from "@/hooks/use-me";
import { Can } from "@/hooks/use-permission";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import { flattenTree, useCategories } from "@/lib/api/queries/categories";
import { queryKeys } from "@/lib/api/queries/keys";
import { useProduct } from "@/lib/api/queries/products";
import { useStockFor } from "@/lib/api/queries/stock";
import type { Schemas } from "@/lib/api/schema";
import { compareDecimal, parseDecimalInput, rateToPercent } from "@/lib/decimal";
import {
  formatDate,
  formatDateTime,
  formatMoney,
  formatQty,
  formatQtyWithUnit,
} from "@/lib/format";
import { labels } from "@/lib/labels";
import { cn } from "@/lib/utils";

type Product = Schemas["ProductRead"];

export function ProductDetailView({ productId }: { productId: string }) {
  const { timeZone, currency } = useCompanyLocale();
  const product = useProduct(productId);
  const categories = useCategories();
  const categoryPath = useMemo(
    () => new Map(flattenTree(categories.data ?? []).map((node) => [node.id, node.path])),
    [categories.data],
  );
  const stock = useStockFor([productId]);
  const prices = useQuery({
    queryKey: queryKeys.products.prices(productId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/products/{product_id}/prices", {
          params: { path: { product_id: productId }, query: { page_size: 20 } },
        }),
      ),
  });
  const movements = useQuery({
    queryKey: queryKeys.movements.list({ product_id: productId, page_size: 8 }),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/inventory/movements", {
          params: { query: { product_id: productId, page_size: 8 } },
        }),
      ),
  });
  const [priceOpen, setPriceOpen] = useState(false);
  const [adjustOpen, setAdjustOpen] = useState(false);

  if (product.isError) {
    return <ErrorState error={product.error} onRetry={() => void product.refetch()} />;
  }
  if (!product.data) return <Skeleton className="h-96 w-full" />;

  const data = product.data;
  const line = stock.data?.get(data.id);

  return (
    <>
      <Link
        href="/products"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" aria-hidden />
        {labels.products.backToList}
      </Link>
      <PageHeader
        title={data.name}
        count={
          <span className="flex flex-wrap items-center gap-2">
            <span className="numeric">{data.sku}</span>
            {!data.is_active && <Badge variant="neutral">{labels.products.inactiveBadge}</Badge>}
            {line && <StockStatusBadge status={line.status} />}
          </span>
        }
        actions={
          <>
            <Can permission="products:update">
              <Button variant="outline" asChild>
                <Link href={`/products/${data.id}/edit`}>
                  <Pencil aria-hidden />
                  {labels.products.edit}
                </Link>
              </Button>
            </Can>
            <Can permission="prices:create">
              <Button variant="outline" onClick={() => setPriceOpen(true)}>
                <Tag aria-hidden />
                {labels.products.changePrice}
              </Button>
            </Can>
            {data.is_stock_tracked && (
              <Can permission="inventory:update">
                <Button onClick={() => setAdjustOpen(true)}>
                  <Boxes aria-hidden />
                  {labels.products.adjustStock}
                </Button>
              </Can>
            )}
          </>
        }
      />

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>{labels.products.priceHistory}</CardTitle>
            </CardHeader>
            <CardContent>
              {prices.data ? (
                <ol className="relative space-y-4 border-l pl-6">
                  {prices.data.items.map((price) => {
                    const current = price.valid_to === null;
                    return (
                      <li key={price.id} className="relative">
                        <span
                          aria-hidden
                          className={cn(
                            "absolute top-1.5 -left-[31px] size-3 rounded-full border-2 border-card",
                            current ? "bg-primary" : "bg-muted-foreground/40",
                          )}
                        />
                        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                          <Money
                            value={price.unit_price}
                            currency={currency}
                            className={cn("text-base", current && "font-semibold")}
                          />
                          {current && <Badge variant="info">{labels.products.current}</Badge>}
                          {price.cost_price && (
                            <span className="text-sm text-muted-foreground">
                              {labels.products.costPrice(formatMoney(price.cost_price, currency))}
                            </span>
                          )}
                        </div>
                        <p className="text-sm numeric text-muted-foreground">
                          {current
                            ? labels.products.priceFrom(formatDateTime(price.valid_from, timeZone))
                            : labels.products.priceRange(
                                formatDateTime(price.valid_from, timeZone),
                                formatDateTime(price.valid_to, timeZone),
                              )}
                        </p>
                      </li>
                    );
                  })}
                </ol>
              ) : (
                <Skeleton className="h-24 w-full" />
              )}
            </CardContent>
          </Card>

          {data.is_stock_tracked && (
            <Card>
              <CardHeader>
                <CardTitle>{labels.products.lastMovements}</CardTitle>
                <CardAction>
                  <Link
                    href={`/inventory?tab=journal&product=${data.id}`}
                    className="text-sm font-medium text-primary hover:underline"
                  >
                    {labels.products.seeJournal}
                  </Link>
                </CardAction>
              </CardHeader>
              <CardContent>
                {!movements.data ? (
                  <Skeleton className="h-24 w-full" />
                ) : movements.data.items.length === 0 ? (
                  <p className="text-sm text-muted-foreground">{labels.products.noMovements}</p>
                ) : (
                  <ul className="divide-y">
                    {movements.data.items.map((movement) => {
                      const positive = compareDecimal(movement.qty_delta, "0") === 1;
                      return (
                        <li
                          key={movement.id}
                          className="flex items-center justify-between gap-3 py-2"
                        >
                          <div className="min-w-0">
                            <p className="font-medium">
                              {labels.stock.movementTypes[movement.type]}
                            </p>
                            <p className="truncate text-sm text-muted-foreground">
                              <span className="numeric">
                                {formatDateTime(movement.occurred_at, timeZone)}
                              </span>
                              {movement.note && ` · ${movement.note}`}
                            </p>
                          </div>
                          <span
                            className={cn(
                              "font-medium numeric",
                              positive ? "text-success" : "text-destructive",
                            )}
                          >
                            {positive ? "+" : ""}
                            {formatQty(movement.qty_delta)}
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </CardContent>
            </Card>
          )}
        </div>

        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>{labels.products.sheet}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <Row label={labels.products.unitPrice}>
                {data.unit_price ? (
                  <Money value={data.unit_price} currency={currency} className="font-semibold" />
                ) : (
                  labels.products.noPrice
                )}
              </Row>
              <Row label={labels.products.category}>
                {(data.category_id && categoryPath.get(data.category_id)) ?? "—"}
              </Row>
              <Row label={labels.products.barcode}>
                <span className="numeric">{data.barcode ?? "—"}</span>
              </Row>
              <Row label={labels.products.unit}>{labels.units[data.unit]}</Row>
              <Row label={labels.products.taxRate}>
                <span className="numeric">{rateToPercent(data.default_tax_rate)} %</span>
              </Row>
              <Row label={labels.products.reorderPoint}>
                <span className="numeric">{formatQty(data.reorder_point)}</span>
              </Row>
              <Row label={labels.products.stockTracked}>
                {data.is_stock_tracked ? labels.products.yes : labels.products.no}
              </Row>
              <Row label={labels.products.createdAt}>
                <span className="numeric">{formatDate(data.created_at, timeZone)}</span>
              </Row>
            </CardContent>
          </Card>

          {data.is_stock_tracked && (
            <Card>
              <CardHeader>
                <CardTitle>{labels.products.stock}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                {line ? (
                  <>
                    <Row label={labels.products.qtyOnHand}>
                      <span className="text-figure-sm numeric">
                        {formatQtyWithUnit(
                          line.qty_on_hand,
                          labels.units[data.unit],
                          labels.unitsPlural[data.unit],
                        )}
                      </span>
                    </Row>
                    <Row label={labels.products.avgCost}>
                      <Money value={line.avg_cost} currency={currency} />
                    </Row>
                    <Row label={labels.products.stockValue}>
                      <Money value={line.stock_value} currency={currency} />
                    </Row>
                  </>
                ) : (
                  <p className="text-muted-foreground">{labels.products.noMovement}</p>
                )}
              </CardContent>
            </Card>
          )}
        </div>
      </div>

      <PriceDialog product={data} open={priceOpen} onOpenChange={setPriceOpen} />
      <MovementDialog
        open={adjustOpen}
        onOpenChange={setAdjustOpen}
        product={{ id: data.id, name: data.name, sku: data.sku }}
        defaultType="adjustment"
      />
    </>
  );
}

function PriceDialog({
  product,
  open,
  onOpenChange,
}: {
  product: Product;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const [price, setPrice] = useState("");
  const [cost, setCost] = useState("");
  const [errors, setErrors] = useState<{ price?: string; cost?: string; form?: string }>({});

  const change = useMutation({
    meta: { toastError: false },
    mutationFn: (body: Schemas["ProductPriceCreate"]) =>
      unwrap(
        api.POST("/api/v1/products/{product_id}/prices", {
          params: { path: { product_id: product.id } },
          body,
        }),
      ),
    onSuccess: () => {
      for (const key of [queryKeys.products.all]) {
        void queryClient.invalidateQueries({ queryKey: key });
      }
      toast.success(labels.products.priceSaved);
      setPrice("");
      setCost("");
      onOpenChange(false);
    },
    onError: (error) => setErrors({ form: errorMessage(error) }),
  });

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) setErrors({});
        onOpenChange(next);
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{labels.products.priceTitle}</DialogTitle>
          <DialogDescription>{labels.products.priceDescription}</DialogDescription>
        </DialogHeader>
        <form
          noValidate
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            const unitPrice = parseDecimalInput(price);
            const costPrice = cost.trim() ? parseDecimalInput(cost) : null;
            const next: typeof errors = {};
            if (unitPrice === null || compareDecimal(unitPrice, "0") !== 1) {
              next.price = labels.sales.invalidNumber;
            }
            if (cost.trim() && costPrice === null) next.cost = labels.sales.invalidNumber;
            setErrors(next);
            if (Object.keys(next).length > 0 || unitPrice === null) return;
            change.mutate({ unit_price: unitPrice, cost_price: costPrice });
          }}
        >
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="new-price">{labels.products.newPrice}</Label>
              <Input
                id="new-price"
                inputMode="decimal"
                value={price}
                aria-invalid={Boolean(errors.price)}
                onChange={(event) => setPrice(event.target.value)}
                className="text-right numeric"
              />
              <FieldError message={errors.price} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="new-cost">{labels.products.newCost}</Label>
              <Input
                id="new-cost"
                inputMode="decimal"
                value={cost}
                aria-invalid={Boolean(errors.cost)}
                onChange={(event) => setCost(event.target.value)}
                className="text-right numeric"
              />
              <FieldError message={errors.cost} />
            </div>
          </div>
          <FieldError message={errors.form} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {labels.common.close}
            </Button>
            <Button type="submit" disabled={change.isPending}>
              {labels.common.save}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right">{children}</span>
    </div>
  );
}
