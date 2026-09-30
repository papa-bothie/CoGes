"use client";

import { useIsMutating, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, UserRound, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { ErrorState } from "@/components/error-state";
import { FieldError } from "@/components/field-error";
import { Money } from "@/components/money";
import { PageHeader } from "@/components/page-header";
import { SearchCombobox } from "@/components/search-combobox";
import { SaleStatusBadge } from "@/components/status/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useCompanyLocale, useMe } from "@/hooks/use-me";
import { api, unwrap } from "@/lib/api/client";
import { isApiError, errorMessage } from "@/lib/api/errors";
import { useIdempotencyKey } from "@/lib/api/idempotency";
import { queryKeys } from "@/lib/api/queries/keys";
import { useStockFor, type StockLine } from "@/lib/api/queries/stock";
import type { Schemas } from "@/lib/api/schema";
import { compareDecimal, parseDecimalInput } from "@/lib/decimal";
import { formatMoney, formatQty } from "@/lib/format";
import { dayEndIso } from "@/lib/format/zoned";
import { labels } from "@/lib/labels";
import { cn } from "@/lib/utils";

import { SaleLineRow, type LineChange } from "./sale-line-row";

type SaleDetail = Schemas["SaleDetail"];
type Product = Schemas["ProductRead"];
type Customer = Schemas["CustomerRead"];
type PaymentMethod = Schemas["PaymentMethod"];
type Mode = "full" | "partial" | "credit";

const METHODS: readonly PaymentMethod[] = [
  "cash",
  "mobile_money",
  "bank_transfer",
  "card",
  "cheque",
];
const MODES: readonly Mode[] = ["full", "partial", "credit"];

/** Refus de la confirmation qui concernent le règlement plutôt qu'une ligne. */
const SETTLEMENT_ERRORS = new Set([
  "credit_limit_exceeded",
  "customer_required_for_credit",
  "overpayment",
]);

type ProductHit = { product: Product; stock: StockLine | undefined };

async function searchProducts(text: string): Promise<ProductHit[]> {
  const page = await unwrap(
    api.GET("/api/v1/products", {
      params: { query: { search: text || undefined, is_active: true, page_size: 8 } },
    }),
  );
  const ids = page.items.map((product) => product.id);
  const stock = ids.length
    ? await unwrap(
        api.GET("/api/v1/inventory/stock", {
          params: { query: { product_id: ids, page_size: 100 } },
        }),
      )
    : { items: [] };
  const byProduct = new Map(stock.items.map((line) => [line.product_id, line]));
  return page.items.map((product) => ({ product, stock: byProduct.get(product.id) }));
}

async function searchCustomers(text: string): Promise<Customer[]> {
  const page = await unwrap(
    api.GET("/api/v1/customers", {
      params: { query: { search: text || undefined, page_size: 8 } },
    }),
  );
  return page.items;
}

/**
 * Saisie d'une vente. Le brouillon naît **côté serveur** au premier article, chaque
 * modification y est synchronisée, et les totaux affichés sont ceux qu'il renvoie : le
 * front ne calcule aucun montant. Seule la confirmation touche au stock et à l'argent.
 */
export function SaleEditor({ saleId: initialId }: { saleId?: string }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { data: me } = useMe();
  const { currency } = useCompanyLocale();
  const timeZone = me?.company.timezone ?? "UTC";
  const showTax = me?.company.tax_enabled ?? true;

  const [saleId, setSaleId] = useState(initialId);
  const [pendingCustomer, setPendingCustomer] = useState<Customer | null>(null);
  const [lineErrors, setLineErrors] = useState<Record<string, string>>({});
  const [articleError, setArticleError] = useState<string | null>(null);
  const [settlementError, setSettlementError] = useState<string | null>(null);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode>("full");
  const [paidInput, setPaidInput] = useState("");
  const [method, setMethod] = useState<PaymentMethod>("cash");
  const [dueDate, setDueDate] = useState("");
  const idempotency = useIdempotencyKey();

  const sale = useQuery({
    queryKey: queryKeys.sales.detail(saleId ?? "new"),
    queryFn: () =>
      unwrap(api.GET("/api/v1/sales/{sale_id}", { params: { path: { sale_id: saleId! } } })),
    enabled: Boolean(saleId),
  });
  const data = sale.data;
  const items = useMemo(() => data?.items ?? [], [data]);
  const productIds = useMemo(() => items.map((item) => item.product_id), [items]);
  const stock = useStockFor(productIds);
  const mutating = useIsMutating({ mutationKey: ["sale-editor"] }) > 0;

  // Une vente confirmée ou annulée ne se modifie plus : on montre son détail.
  useEffect(() => {
    if (data && data.status !== "draft") router.replace(`/sales/${data.id}`);
  }, [data, router]);

  const refresh = (id: string) =>
    queryClient.invalidateQueries({ queryKey: queryKeys.sales.detail(id) });

  const ensureSale = async (): Promise<string> => {
    if (saleId) return saleId;
    const created = await unwrap(
      api.POST("/api/v1/sales", { body: { customer_id: pendingCustomer?.id ?? null } }),
    );
    queryClient.setQueryData(queryKeys.sales.detail(created.id), created);
    setSaleId(created.id);
    // L'URL suit le brouillon sans remonter le composant : un rechargement le reprend.
    window.history.replaceState(null, "", `/sales/${created.id}/edit`);
    void queryClient.invalidateQueries({ queryKey: queryKeys.sales.all, exact: false });
    return created.id;
  };

  const addItem = useMutation({
    mutationKey: ["sale-editor", "add"],
    meta: { toastError: false },
    mutationFn: async (product: Product) => {
      const id = await ensureSale();
      await unwrap(
        api.POST("/api/v1/sales/{sale_id}/items", {
          params: { path: { sale_id: id } },
          body: { product_id: product.id, qty: "1", discount: "0" },
        }),
      );
      return id;
    },
    onMutate: () => setArticleError(null),
    onSuccess: (id) => refresh(id),
    onError: (error) => setArticleError(errorMessage(error)),
  });

  const updateItem = useMutation({
    mutationKey: ["sale-editor", "update"],
    meta: { toastError: false },
    mutationFn: ({ itemId, change }: { itemId: string; change: LineChange }) =>
      unwrap(
        api.PATCH("/api/v1/sales/{sale_id}/items/{item_id}", {
          params: { path: { sale_id: saleId!, item_id: itemId } },
          body: change,
        }),
      ),
    onMutate: ({ itemId }) => setLineErrors((current) => without(current, itemId)),
    onError: (error, { itemId }) =>
      setLineErrors((current) => ({ ...current, [itemId]: errorMessage(error) })),
    onSettled: () => saleId && refresh(saleId),
  });

  const removeItem = useMutation({
    mutationKey: ["sale-editor", "remove"],
    mutationFn: (itemId: string) =>
      unwrap(
        api.DELETE("/api/v1/sales/{sale_id}/items/{item_id}", {
          params: { path: { sale_id: saleId!, item_id: itemId } },
        }),
      ),
    onSuccess: (_, itemId) => setLineErrors((current) => without(current, itemId)),
    onSettled: () => saleId && refresh(saleId),
  });

  const setCustomer = useMutation({
    mutationKey: ["sale-editor", "customer"],
    mutationFn: (customer: Customer | null) =>
      unwrap(
        api.PATCH("/api/v1/sales/{sale_id}", {
          params: { path: { sale_id: saleId! } },
          body: { customer_id: customer?.id ?? null },
        }),
      ),
    onSuccess: (updated) => queryClient.setQueryData(queryKeys.sales.detail(updated.id), updated),
  });

  const chooseCustomer = (customer: Customer | null) => {
    setSettlementError(null);
    if (saleId) setCustomer.mutate(customer);
    else setPendingCustomer(customer);
  };

  const shortProducts = useMemo(() => {
    const short = new Set<string>();
    for (const item of items) {
      const line = stock.data?.get(item.product_id);
      if (line && compareDecimal(item.qty, line.qty_on_hand) === 1) short.add(item.product_id);
    }
    return short;
  }, [items, stock.data]);

  const paidAmount = (): string | null => {
    if (!data) return null;
    if (mode === "full") return data.total;
    if (mode === "credit") return "0";
    return parseDecimalInput(paidInput);
  };

  const confirm = useMutation({
    mutationKey: ["sale-editor", "confirm"],
    meta: { toastError: false },
    mutationFn: (body: Schemas["SaleConfirm"]) =>
      unwrap(
        api.POST("/api/v1/sales/{sale_id}/confirm", {
          params: { path: { sale_id: saleId! } },
          body,
          headers: idempotency.headers,
        }),
      ),
    onMutate: () => {
      setConfirmError(null);
      setSettlementError(null);
    },
    onSuccess: (confirmed: SaleDetail) => {
      idempotency.renew();
      queryClient.setQueryData(queryKeys.sales.detail(confirmed.id), confirmed);
      for (const key of [queryKeys.sales.all, queryKeys.stock.all, queryKeys.dashboard]) {
        void queryClient.invalidateQueries({ queryKey: key });
      }
      toast.success(labels.sales.confirmed(confirmed.sale_no));
      router.push(`/sales/${confirmed.id}`);
    },
    onError: (error) => {
      if (isApiError(error) && error.code === "insufficient_stock") {
        const productId = String(error.details.product_id ?? "");
        const available = formatQty(String(error.details.available ?? ""));
        const item = items.find((line) => line.product_id === productId);
        if (item) {
          setLineErrors((current) => ({
            ...current,
            [item.id]: labels.sales.insufficient(available),
          }));
          void queryClient.invalidateQueries({ queryKey: queryKeys.stock.all });
          return;
        }
      }
      if (isApiError(error) && SETTLEMENT_ERRORS.has(error.code)) {
        setSettlementError(error.message);
        return;
      }
      setConfirmError(errorMessage(error));
    },
  });

  const submitConfirm = () => {
    const paid = paidAmount();
    if (paid === null) {
      setSettlementError(labels.sales.invalidNumber);
      return;
    }
    confirm.mutate({
      paid_amount: paid,
      method,
      due_date: mode !== "full" && dueDate ? dayEndIso(dueDate, timeZone) : null,
    });
  };

  if (saleId && sale.isError) {
    return <ErrorState error={sale.error} onRetry={() => void sale.refetch()} />;
  }

  const loadingDraft = Boolean(saleId) && sale.isPending;
  const customerName = saleId ? data?.customer_name : pendingCustomer?.name;
  const customerId = saleId ? data?.customer_id : pendingCustomer?.id;
  const busy = mutating || sale.isFetching;
  const canConfirm =
    Boolean(data) && items.length > 0 && shortProducts.size === 0 && !busy && !confirm.isPending;

  return (
    <>
      <PageHeader
        title={data ? labels.sales.editTitle(data.sale_no) : labels.sales.newSale}
        count={data && <SaleStatusBadge status={data.status} hasReturns={data.has_returns} />}
      />

      {/* Sous `xl`, la barre d'actions est fixée en bas : on réserve sa hauteur. */}
      <div className="grid items-start gap-6 pb-28 xl:grid-cols-[minmax(0,1fr)_20rem] xl:pb-0">
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>{labels.sales.customer}</CardTitle>
            </CardHeader>
            <CardContent>
              {loadingDraft ? (
                <Skeleton className="h-9 w-full" />
              ) : customerId ? (
                <div className="flex items-center justify-between gap-3 rounded-lg border px-3 py-2">
                  <span className="flex items-center gap-2 font-medium">
                    <UserRound className="size-4 text-muted-foreground" aria-hidden />
                    {customerName}
                  </span>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={labels.sales.removeCustomer}
                    disabled={setCustomer.isPending}
                    onClick={() => chooseCustomer(null)}
                  >
                    <X />
                  </Button>
                </div>
              ) : (
                <>
                  <SearchCombobox
                    label={labels.sales.customerSearch}
                    queryKey={queryKeys.customers.search}
                    search={searchCustomers}
                    itemKey={(customer) => customer.id}
                    onSelect={chooseCustomer}
                    disabled={setCustomer.isPending}
                    renderItem={(customer) => (
                      <span className="flex justify-between gap-3">
                        <span>{customer.name}</span>
                        <span className="numeric text-muted-foreground">{customer.code}</span>
                      </span>
                    )}
                  />
                  <p className="mt-2 text-sm text-muted-foreground">{labels.sales.noCustomer}</p>
                </>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>{labels.sales.articles}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <SearchCombobox
                label={labels.sales.productSearch}
                queryKey={queryKeys.products.search}
                search={searchProducts}
                itemKey={(hit) => hit.product.id}
                disabled={addItem.isPending || loadingDraft}
                onSelect={(hit) => {
                  if (items.some((item) => item.product_id === hit.product.id)) {
                    setArticleError(labels.sales.alreadyInSale);
                    return;
                  }
                  addItem.mutate(hit.product);
                }}
                renderItem={({ product, stock: line }) => (
                  <span className="flex items-center justify-between gap-3">
                    <span className="min-w-0">
                      <span className="block truncate font-medium">{product.name}</span>
                      <span className="text-xs numeric text-muted-foreground">{product.sku}</span>
                    </span>
                    <span className="text-right">
                      <span className="block numeric whitespace-nowrap">
                        {formatMoney(product.unit_price, currency)}
                      </span>
                      <span
                        className={cn(
                          "text-xs numeric",
                          line?.status === "out" ? "text-destructive" : "text-muted-foreground",
                        )}
                      >
                        {line ? `${formatQty(line.qty_on_hand)} en stock` : "—"}
                      </span>
                    </span>
                  </span>
                )}
              />
              <FieldError message={articleError} />

              {loadingDraft ? (
                <Skeleton className="h-24 w-full" />
              ) : items.length === 0 ? (
                <p className="rounded-lg border border-dashed px-4 py-8 text-center text-sm text-muted-foreground">
                  {labels.sales.noLines}
                </p>
              ) : (
                <div className="overflow-x-auto rounded-lg border">
                  <Table>
                    <TableHeader>
                      <TableRow className="hover:bg-transparent">
                        <TableHead className="px-3">{labels.sales.lineColumns.product}</TableHead>
                        <TableHead className="px-3 text-right">
                          {labels.sales.lineColumns.unitPrice}
                        </TableHead>
                        <TableHead className="px-3 text-right">
                          {labels.sales.lineColumns.qty}
                        </TableHead>
                        <TableHead className="px-3 text-right">
                          {labels.sales.lineColumns.discount}
                        </TableHead>
                        {showTax && (
                          <TableHead className="px-3 text-right">
                            {labels.sales.lineColumns.tax}
                          </TableHead>
                        )}
                        <TableHead className="px-3 text-right">
                          {labels.sales.lineColumns.total}
                        </TableHead>
                        <TableHead className="w-10 px-2">
                          <span className="sr-only">Actions</span>
                        </TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {items.map((item) => {
                        const line = stock.data?.get(item.product_id);
                        const short = shortProducts.has(item.product_id);
                        return (
                          <SaleLineRow
                            key={item.id}
                            item={item}
                            currency={currency}
                            showTax={showTax}
                            stock={line}
                            short={short}
                            error={
                              lineErrors[item.id] ??
                              (short && line
                                ? labels.sales.insufficient(formatQty(line.qty_on_hand))
                                : undefined)
                            }
                            disabled={confirm.isPending}
                            onChange={(change) => updateItem.mutate({ itemId: item.id, change })}
                            onRemove={() => removeItem.mutate(item.id)}
                          />
                        );
                      })}
                    </TableBody>
                  </Table>
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        <div className="grid items-start gap-6 md:grid-cols-2 xl:sticky xl:top-20 xl:block xl:space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>{labels.sales.totals}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <TotalRow label={labels.sales.subtotal} value={data?.subtotal} currency={currency} />
              <TotalRow
                label={labels.sales.discounts}
                value={data?.discount_total}
                currency={currency}
              />
              {showTax && (
                <TotalRow label={labels.sales.taxes} value={data?.tax_total} currency={currency} />
              )}
              <div className="flex items-baseline justify-between border-t pt-3">
                <span className="font-semibold">{labels.sales.total}</span>
                <Money value={data?.total ?? "0"} currency={currency} className="text-figure-sm" />
              </div>
              <p
                aria-live="polite"
                className="flex items-center gap-1.5 text-xs text-muted-foreground"
              >
                {busy ? (
                  <>
                    <Loader2 className="size-3 animate-spin" aria-hidden />
                    {labels.sales.updating}
                  </>
                ) : (
                  labels.sales.upToDate
                )}
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>{labels.sales.settlement}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div
                role="radiogroup"
                aria-label={labels.sales.settlement}
                className="grid grid-cols-3 gap-1 rounded-lg bg-muted p-1"
              >
                {MODES.map((value) => (
                  <button
                    key={value}
                    type="button"
                    role="radio"
                    aria-checked={mode === value}
                    onClick={() => {
                      setMode(value);
                      setSettlementError(null);
                    }}
                    className={cn(
                      "rounded-md px-2 py-1.5 text-sm font-medium outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                      mode === value
                        ? "bg-card text-foreground shadow-sm"
                        : "text-muted-foreground hover:text-foreground",
                    )}
                  >
                    {labels.sales.settlementModes[value]}
                  </button>
                ))}
              </div>

              {mode === "partial" && (
                <div className="space-y-1.5">
                  <Label htmlFor="paid-amount">{labels.sales.paidAmount}</Label>
                  <Input
                    id="paid-amount"
                    inputMode="decimal"
                    value={paidInput}
                    onChange={(event) => setPaidInput(event.target.value)}
                    className="h-9 text-right numeric"
                  />
                </div>
              )}

              {mode !== "credit" && (
                <div className="space-y-1.5">
                  <Label htmlFor="payment-method">{labels.sales.method}</Label>
                  <Select
                    value={method}
                    onValueChange={(value) => setMethod(value as PaymentMethod)}
                  >
                    <SelectTrigger id="payment-method" className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {METHODS.map((value) => (
                        <SelectItem key={value} value={value}>
                          {labels.paymentMethods[value]}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )}

              {mode !== "full" && (
                <>
                  <div className="space-y-1.5">
                    <Label htmlFor="due-date">{labels.sales.dueDate}</Label>
                    <Input
                      id="due-date"
                      type="date"
                      value={dueDate}
                      onChange={(event) => setDueDate(event.target.value)}
                      className="h-9"
                    />
                  </div>
                  <p className="text-sm text-muted-foreground">
                    {customerId
                      ? labels.sales.balanceBecomesDebt
                      : labels.sales.creditNeedsCustomer}
                  </p>
                </>
              )}
              <FieldError message={settlementError} />
            </CardContent>
          </Card>

          {/*
            Actions : sous la colonne à partir de `xl` ; en dessous (tablette), barre fixée en
            bas avec le total, pour que « Confirmer la vente » reste toujours à portée.
          */}
          <div className="space-y-2 max-xl:fixed max-xl:inset-x-0 max-xl:bottom-0 max-xl:z-20 max-xl:border-t max-xl:bg-card max-xl:px-4 max-xl:py-3 max-xl:shadow-lg md:max-xl:px-6 lg:max-xl:left-52 print:hidden">
            <div className="flex flex-wrap items-center gap-2 xl:flex-col xl:items-stretch">
              <div className="mr-auto min-w-0 xl:hidden">
                <p className="text-xs text-muted-foreground">{labels.sales.total}</p>
                <Money value={data?.total ?? "0"} currency={currency} className="text-figure-sm" />
              </div>
              <Button
                className="max-xl:order-last xl:w-full"
                size="lg"
                disabled={!canConfirm}
                onClick={submitConfirm}
              >
                {confirm.isPending && <Loader2 className="animate-spin" aria-hidden />}
                {confirm.isPending ? labels.sales.confirming : labels.sales.confirm}
              </Button>
              <Button
                variant="outline"
                className="xl:order-last xl:w-full"
                disabled={!saleId || busy}
                onClick={() => {
                  toast.success(labels.sales.draftSaved);
                  router.push("/sales");
                }}
              >
                {labels.sales.saveDraft}
              </Button>
            </div>
            {shortProducts.size > 0 && (
              <p className="text-sm text-destructive">{labels.sales.confirmBlocked}</p>
            )}
            <FieldError message={confirmError} />
          </div>
        </div>
      </div>
    </>
  );
}

function without(record: Record<string, string>, key: string): Record<string, string> {
  const next = { ...record };
  delete next[key];
  return next;
}

function TotalRow({
  label,
  value,
  currency,
}: {
  label: string;
  value: string | undefined;
  currency: string;
}) {
  return (
    <div className="flex items-baseline justify-between">
      <span className="text-muted-foreground">{label}</span>
      <Money value={value ?? "0"} currency={currency} />
    </div>
  );
}
