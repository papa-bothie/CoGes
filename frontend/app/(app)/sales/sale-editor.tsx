"use client";

import { useIsMutating, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { ErrorState } from "@/components/error-state";
import { FieldError } from "@/components/field-error";
import { AmountField, cleanAmount } from "@/components/kit/amount-field";
import { PaymentAmount } from "@/components/kit/payment-amount";
import { PaymentMethodChips } from "@/components/kit/payment-method-chips";
import { CustomerPicker, type PickedCustomer } from "@/components/sales/customer-picker";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { useCompanyLocale, useMe } from "@/hooks/use-me";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage, isApiError } from "@/lib/api/errors";
import { useIdempotencyKey } from "@/lib/api/idempotency";
import { queryKeys } from "@/lib/api/queries/keys";
import { useStockFor } from "@/lib/api/queries/stock";
import type { Schemas } from "@/lib/api/schema";
import { compareDecimal, toInputDecimal } from "@/lib/decimal";
import { formatAmount, formatFigure, formatQty } from "@/lib/format";
import { dayEndIso, dayStartIso } from "@/lib/format/zoned";
import { labels } from "@/lib/labels";
import {
  billShortcuts,
  changeDue,
  partPaymentCheck,
  partShortcuts,
  typedAmount,
  wholeUnits,
} from "@/lib/payment-amount";
import { todayIn } from "@/lib/period";
import { cn } from "@/lib/utils";

import { ProductGrid } from "./product-grid";
import { SaleSuccess } from "./sale-success";
import { TicketLine, type LineChange } from "./ticket-line";

type SaleDetail = Schemas["SaleDetail"];
type Product = Schemas["ProductRead"];
type PaymentMethod = Schemas["PaymentMethod"];
type Mode = "full" | "partial" | "credit";
type Done = { sale: SaleDetail; line: string; phone: string | null };

const MODES: readonly Mode[] = ["full", "partial", "credit"];
const t = labels.sales.editor;

/** Refus de la confirmation qui concernent le règlement plutôt qu'une ligne. */
const SETTLEMENT_ERRORS = new Set([
  "credit_limit_exceeded",
  "customer_required_for_credit",
  "overpayment",
]);

/**
 * « Nouvelle vente » de la maquette v2 (écran 02), pensée caisse : on touche des tuiles, on
 * choisit comment le client paie, on encaisse. Aucune saisie clavier n'est nécessaire.
 *
 * Le brouillon naît **côté serveur** au premier article et chaque toucher y est synchronisé
 * (ADR 0052) : les totaux affichés sont ceux du serveur, le front ne calcule aucun montant
 * de vente. Seule la confirmation touche au stock et à l'argent, sous une clé d'idempotence
 * gardée jusqu'au succès. Après la confirmation, l'écran de succès (02d).
 */
export function SaleEditor({
  saleId: initialId,
  customerId: askedCustomerId,
}: {
  saleId?: string;
  /** « Lui vendre » depuis une fiche client (écran 14) : ce client est déjà choisi. */
  customerId?: string;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { data: me } = useMe();
  const { currency } = useCompanyLocale();
  const timeZone = me?.company.timezone ?? "UTC";

  const [saleId, setSaleId] = useState(initialId);
  const [pendingCustomer, setPendingCustomer] = useState<PickedCustomer | null>(null);
  const [customerPhone, setCustomerPhone] = useState<string | null>(null);
  const [changingCustomer, setChangingCustomer] = useState(false);
  const [lineErrors, setLineErrors] = useState<Record<string, string>>({});
  const [articleError, setArticleError] = useState<string | null>(null);
  const [settlementError, setSettlementError] = useState<string | null>(null);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode>("full");
  const [paidInput, setPaidInput] = useState("");
  const [given, setGiven] = useState("");
  const [method, setMethod] = useState<PaymentMethod>("cash");
  const [dueDate, setDueDate] = useState("");
  const [done, setDone] = useState<Done | null>(null);
  const idempotency = useIdempotencyKey();

  // « Nouvelle vente » reprend le brouillon du jour de la même personne : un panier
  // interrompu (coupure, mauvais clic) n'est pas perdu. Une seule fois, à l'ouverture.
  const [resuming, setResuming] = useState(!initialId);
  const resume = useQuery({
    queryKey: queryKeys.sales.list({ resume: true, timeZone }),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/sales", {
          params: {
            query: {
              status: "draft",
              mine: true,
              date_from: dayStartIso(todayIn(timeZone), timeZone) ?? undefined,
              page_size: 1,
            },
          },
        }),
      ),
    enabled: resuming && Boolean(me),
    staleTime: 0,
  });
  const [resumedId, setResumedId] = useState<string | null>(null);
  if (resuming && resume.data) {
    setResuming(false);
    const draft = resume.data.items[0];
    if (draft && !saleId) {
      setSaleId(draft.id);
      setResumedId(draft.id);
    }
  }
  if (resuming && resume.isError) setResuming(false);
  // L'URL suit le brouillon repris, hors du rendu : le routeur de Next écoute l'historique.
  useEffect(() => {
    if (resumedId) window.history.replaceState(null, "", `/sales/${resumedId}/edit`);
  }, [resumedId]);

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

  // Une vente confirmée ou annulée ne se modifie plus : on montre son détail (sauf juste
  // après l'encaissement, où l'écran de succès prend la place).
  useEffect(() => {
    if (data && data.status !== "draft" && !done) router.replace(`/sales/${data.id}`);
  }, [data, done, router]);

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
    mutationFn: (customer: PickedCustomer | null) =>
      unwrap(
        api.PATCH("/api/v1/sales/{sale_id}", {
          params: { path: { sale_id: saleId! } },
          body: { customer_id: customer?.id ?? null },
        }),
      ),
    onSuccess: (updated) => queryClient.setQueryData(queryKeys.sales.detail(updated.id), updated),
  });

  const chooseCustomer = (customer: PickedCustomer | null) => {
    setSettlementError(null);
    setChangingCustomer(false);
    setCustomerPhone(customer?.phone ?? null);
    if (saleId) setCustomer.mutate(customer);
    else setPendingCustomer(customer);
  };

  // Le client venu de sa fiche se pose une fois le brouillon du jour repris (ou non).
  const asked = useQuery({
    queryKey: queryKeys.customers.detail(askedCustomerId ?? "none"),
    enabled: Boolean(askedCustomerId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/customers/{customer_id}", {
          params: { path: { customer_id: askedCustomerId! } },
        }),
      ),
  });
  const askedApplied = useRef(false);
  const saleLoaded = Boolean(sale.data);
  useEffect(() => {
    if (askedApplied.current || resuming || !asked.data || (saleId && !saleLoaded)) return;
    askedApplied.current = true;
    chooseCustomer({ id: asked.data.id, name: asked.data.name, phone: asked.data.phone });
    // `chooseCustomer` change à chaque rendu ; seule l'arrivée du client compte.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resuming, asked.data, saleId, saleLoaded]);

  /** Toucher une tuile : 1 de plus, ou une nouvelle ligne. */
  const addProduct = (product: Product) => {
    const existing = items.find((item) => item.product_id === product.id);
    if (!existing) {
      addItem.mutate(product);
      return;
    }
    const next = (wholeUnits(existing.qty) + 1n).toString();
    updateItem.mutate({ itemId: existing.id, change: { qty: next } });
  };

  const inCart = useMemo(
    () => new Map(items.map((item) => [item.product_id, toInputDecimal(item.qty)])),
    [items],
  );

  const shortProducts = useMemo(() => {
    const short = new Set<string>();
    for (const item of items) {
      const line = stock.data?.get(item.product_id);
      if (line && compareDecimal(item.qty, line.qty_on_hand) === 1) short.add(item.product_id);
    }
    return short;
  }, [items, stock.data]);

  const total = wholeUnits(data?.total);
  const partCheck = partPaymentCheck(paidInput, total, currency);
  const change = changeDue(typedAmount(given), total);
  const customerName = saleId ? data?.customer_name : pendingCustomer?.name;
  const customerId = saleId ? data?.customer_id : pendingCustomer?.id;
  const needCustomer = mode !== "full" && !customerId;

  const paidAmount = (): string | null => {
    if (!data) return null;
    if (mode === "full") return data.total;
    if (mode === "credit") return "0";
    return partCheck.ok ? paidInput : null;
  };

  const successLine = (confirmed: SaleDetail): string => {
    const name = confirmed.customer_name ?? "";
    if (mode === "full") {
      return method === "cash" || method === "wave" || method === "orange_money"
        ? t.success.paid[method]
        : t.success.paid.other(labels.paymentMethods[method]);
    }
    const amount = formatAmount(confirmed.balance, currency);
    return mode === "partial" ? t.success.owesStill(name, amount) : t.success.owes(name, amount);
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
      setDone({ sale: confirmed, line: successLine(confirmed), phone: customerPhone });
      queryClient.setQueryData(queryKeys.sales.detail(confirmed.id), confirmed);
      for (const key of [queryKeys.sales.all, queryKeys.stock.all, queryKeys.dashboard]) {
        void queryClient.invalidateQueries({ queryKey: key });
      }
      void queryClient.invalidateQueries({ queryKey: queryKeys.products.all });
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
      method: mode === "credit" ? "cash" : method,
      due_date: mode !== "full" && dueDate ? dayEndIso(dueDate, timeZone) : null,
    });
  };

  const startNewSale = () => {
    setDone(null);
    setSaleId(undefined);
    setPendingCustomer(null);
    setCustomerPhone(null);
    setMode("full");
    setMethod("cash");
    setPaidInput("");
    setGiven("");
    setDueDate("");
    setLineErrors({});
    window.history.replaceState(null, "", "/sales/new");
  };

  if (done) {
    return (
      <SaleSuccess
        sale={done.sale}
        line={done.line}
        phone={done.phone}
        shop={me?.company.name ?? ""}
        timeZone={timeZone}
        currency={currency}
        onNewSale={startNewSale}
      />
    );
  }

  if (saleId && sale.isError) {
    return <ErrorState error={sale.error} onRetry={() => void sale.refetch()} />;
  }

  const loadingDraft = resuming || (Boolean(saleId) && sale.isPending);
  const busy = mutating || sale.isFetching;
  const blocked =
    !data ||
    items.length === 0 ||
    shortProducts.size > 0 ||
    needCustomer ||
    (mode === "partial" && !partCheck.ok);
  const ctaLabel =
    mode === "credit"
      ? t.saveCredit
      : t.encash(
          formatAmount(mode === "partial" ? paidInput || "0" : (data?.total ?? "0"), currency),
        );

  return (
    <div className="mx-auto flex max-w-[1192px] flex-wrap items-start gap-5">
      <div className="flex min-w-0 flex-[3_1_560px] flex-col gap-2">
        <ProductGrid
          inCart={inCart}
          onAdd={addProduct}
          disabled={addItem.isPending || loadingDraft || confirm.isPending}
          currency={currency}
        />
        <FieldError message={articleError} />
      </div>

      <aside
        aria-label={labels.sales.receipt}
        className="flex min-w-0 flex-[2_1_360px] flex-col gap-[18px] rounded-carte border border-border bg-card p-5"
      >
        <div>
          <p className="mb-2 text-libelle">{t.client}</p>
          {changingCustomer ? (
            <CustomerPicker
              onSelect={chooseCustomer}
              disabled={setCustomer.isPending}
              currency={currency}
              autoOpen
            />
          ) : (
            <button
              type="button"
              onClick={() => setChangingCustomer(true)}
              disabled={setCustomer.isPending || loadingDraft}
              className={cn(
                "flex min-h-16 w-full items-center gap-3 rounded-champ border-2 border-clients bg-clients-teinte px-3 py-2 text-left text-foreground",
                "outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
              )}
            >
              <span
                aria-hidden
                className="flex size-11 shrink-0 items-center justify-center rounded-full bg-clients font-bold text-primary-foreground"
              >
                {customerName ? <InitialsOf name={customerName} /> : "·"}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate font-bold">
                  {customerName ?? labels.kit.walkIn}
                </span>
                <span className="block text-muted-foreground">
                  {customerName ? (customerPhone ?? "") : t.walkInHint}
                </span>
              </span>
              <span className="font-bold text-clients-encre">{t.change}</span>
            </button>
          )}
        </div>

        <div>
          <p className="mb-1 text-libelle">{t.cart}</p>
          {loadingDraft ? (
            <Skeleton className="h-24 w-full" />
          ) : items.length === 0 ? (
            <p className="rounded-[18px] border-2 border-dashed border-input px-2 py-7 text-center text-libelle font-normal text-muted-foreground">
              {t.emptyCart}
            </p>
          ) : (
            items.map((item) => {
              const line = stock.data?.get(item.product_id);
              const short = shortProducts.has(item.product_id);
              return (
                <TicketLine
                  key={item.id}
                  item={item}
                  currency={currency}
                  disabled={confirm.isPending}
                  error={
                    lineErrors[item.id] ??
                    (short && line
                      ? labels.sales.insufficient(formatQty(line.qty_on_hand))
                      : undefined)
                  }
                  onChange={(lineChange) =>
                    updateItem.mutate({ itemId: item.id, change: lineChange })
                  }
                  onRemove={() => removeItem.mutate(item.id)}
                />
              );
            })
          )}
        </div>

        <div className="flex items-baseline justify-between rounded-[18px] bg-ventes-teinte px-[18px] py-4">
          <span className="text-xl font-bold">{t.total}</span>
          <span
            aria-live="polite"
            aria-busy={busy}
            className="text-[36px] leading-tight font-extrabold numeric text-ventes-encre"
          >
            {formatAmount(data?.total ?? "0", currency)}
          </span>
        </div>

        <div>
          <p id="pays" className="mb-2 text-libelle">
            {t.customerPays}
          </p>
          <div role="group" aria-labelledby="pays" className="flex flex-wrap gap-2">
            {MODES.map((value) => (
              <button
                key={value}
                type="button"
                aria-pressed={mode === value}
                onClick={() => {
                  setMode(value);
                  setPaidInput("");
                  setGiven("");
                  setSettlementError(null);
                }}
                className={cn(
                  "min-h-16 flex-[1_1_140px] rounded-[18px] border-2 px-3 py-2 text-libelle",
                  "outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                  mode === value
                    ? "border-ventes bg-ventes text-primary-foreground"
                    : "border-input bg-card text-foreground hover:bg-voile",
                )}
              >
                {labels.sales.settlementModes[value]}
              </button>
            ))}
          </div>
        </div>

        {mode !== "credit" && (
          <PaymentMethodChips
            value={method}
            onChange={setMethod}
            label={t.methods}
            hideLabel
            stretch
            tone="teinte"
          />
        )}

        {mode === "full" && method === "cash" && total > 0n && (
          <div>
            <p id="donne" className="mb-2 text-libelle">
              {labels.payment.customerGives}
            </p>
            <div role="group" aria-labelledby="donne" className="flex flex-wrap gap-2">
              {billShortcuts(total, currency).map((bill) => (
                <button
                  key={bill.value}
                  type="button"
                  aria-pressed={given === bill.value}
                  onClick={() => setGiven(cleanAmount(bill.value))}
                  className={cn(
                    "min-h-cible flex-[1_1_90px] rounded-full border-2 px-[18px] font-semibold numeric",
                    "outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                    given === bill.value
                      ? "border-ventes bg-ventes-teinte text-ventes-encre"
                      : "border-input bg-card text-foreground hover:bg-voile",
                  )}
                >
                  {bill.value === total.toString()
                    ? bill.label
                    : formatFigure(bill.value, currency)}
                </button>
              ))}
            </div>
            <div className="mt-2">
              <AmountField
                label={labels.payment.otherGiven}
                hideLabel
                placeholder={labels.payment.otherGivenPlaceholder}
                size="rendu"
                value={
                  billShortcuts(total, currency).some((bill) => bill.value === given) ? "" : given
                }
                onChange={setGiven}
              />
            </div>
            {change !== null && (
              <p
                role="status"
                className="mt-2.5 flex items-baseline justify-between rounded-champ bg-argent-teinte px-4 py-3"
              >
                <span className="font-bold">{labels.payment.change}</span>
                <span className="text-[26px] font-extrabold numeric text-argent-encre">
                  {formatAmount(change.toString(), currency)}
                </span>
              </p>
            )}
          </div>
        )}

        {mode === "partial" && total > 0n && (
          <PaymentAmount
            id="paid-amount"
            label={labels.payment.givesNow}
            placeholder={labels.payment.typeAmount}
            value={paidInput}
            onChange={setPaidInput}
            shortcuts={partShortcuts(total, currency)}
            check={partCheck}
            okRubrique="stock"
          />
        )}

        {mode !== "full" && customerId && (
          <div className="space-y-1.5">
            <Label htmlFor="due-date" className="text-libelle">
              {labels.sales.dueDate}
            </Label>
            <Input
              id="due-date"
              type="date"
              value={dueDate}
              onChange={(event) => setDueDate(event.target.value)}
              className="h-12 rounded-champ border-2 text-corps"
            />
          </div>
        )}

        {needCustomer && items.length > 0 && (
          <p className="rounded-champ bg-stock-teinte px-4 py-3 font-bold text-stock-encre">
            {t.needCustomer}
          </p>
        )}
        <FieldError message={settlementError} />

        <Button
          variant="ventes"
          size="principal"
          className="w-full text-[21px] font-bold disabled:bg-ventes/45 disabled:opacity-100"
          disabled={blocked || busy || confirm.isPending}
          onClick={submitConfirm}
        >
          {confirm.isPending ? (
            <Loader2 className="size-[26px] animate-spin" aria-hidden />
          ) : (
            <Check className="size-[26px]" aria-hidden />
          )}
          {ctaLabel}
        </Button>
        {shortProducts.size > 0 && (
          <p className="text-sm text-danger-ink">{labels.sales.confirmBlocked}</p>
        )}
        <FieldError message={confirmError} />
      </aside>
    </div>
  );
}

function InitialsOf({ name }: { name: string }) {
  return (
    <>
      {name
        .trim()
        .split(/\s+/)
        .slice(0, 2)
        .map((word) => word.charAt(0).toLocaleUpperCase("fr-FR"))
        .join("")}
    </>
  );
}

function without(record: Record<string, string>, key: string): Record<string, string> {
  const next = { ...record };
  delete next[key];
  return next;
}
