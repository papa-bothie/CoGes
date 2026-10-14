"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Search, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { FieldError } from "@/components/field-error";
import { cleanAmount } from "@/components/kit/amount-field";
import { Chip } from "@/components/kit/chip";
import { ProductSquare } from "@/components/kit/list-row";
import { cleanQuantity } from "@/components/kit/quantity-stepper";
import { fieldClasses } from "@/components/kit/rubrique";
import { PersonFormDialog } from "@/components/people/person-form-dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { useCompanyLocale } from "@/hooks/use-me";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import { useIdempotencyKey } from "@/lib/api/idempotency";
import { queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { compareDecimal, parseDecimalInput } from "@/lib/decimal";
import { formatAmount } from "@/lib/format";
import { labels } from "@/lib/labels";
import { typedAmount, wholeUnits } from "@/lib/payment-amount";
import { addDays, todayIn } from "@/lib/period";
import { qtyWithUnit } from "@/lib/units";
import { cn } from "@/lib/utils";

type StockLine = Schemas["StockLine"];
type Mode = "now" | "part" | "later";
type Method = "cash" | "wave" | "orange_money";
type Line = { product: StockLine; qty: string; cost: string };

const t = labels.stockScreens.delivery;
const MODES: readonly Mode[] = ["now", "part", "later"];
const METHODS: readonly Method[] = ["cash", "wave", "orange_money"];
const DUE_DAYS = [7, 15, 30] as const;

/** Prix d'achat proposé : le prix d'achat moyen, en francs entiers ; vide s'il n'y en a pas. */
function suggestedCost(line: StockLine): string {
  const cost = wholeUnits(line.avg_cost);
  return cost > 0n ? cost.toString() : "";
}

/** Total d'une ligne, en francs entiers (quantité décimale, prix entier). */
function lineTotal(line: Line): bigint {
  const qty = parseDecimalInput(line.qty);
  if (!qty || !line.cost) return 0n;
  const [whole = "0", fraction = ""] = qty.split(".");
  const scaled = BigInt(`${whole}${fraction.padEnd(3, "0").slice(0, 3)}`);
  return (scaled * typedAmount(line.cost) + 500n) / 1000n;
}

/**
 * « Recevoir une livraison », maquette v2 (écran 11) : qui livre, ce qui arrive (quantité et
 * prix d'achat tapés librement), le total, et comment on paie — tout maintenant, une
 * partie, ou plus tard avec une échéance. Une seule écriture, sous clé d'idempotence : le
 * stock, la dette fournisseur et le paiement partent ensemble (ADR 0071).
 */
export function DeliveryForm({
  productId,
  supplierId: askedSupplierId,
}: {
  productId?: string;
  /** « Recevoir une livraison » depuis une fiche fournisseur (écran 16) : déjà choisi. */
  supplierId?: string;
}) {
  const queryClient = useQueryClient();
  const { currency, timeZone } = useCompanyLocale();
  const idempotency = useIdempotencyKey();
  const [supplierId, setSupplierId] = useState<string | null>(askedSupplierId ?? null);
  const [lines, setLines] = useState<Line[]>([]);
  const [seeded, setSeeded] = useState(false);
  const [mode, setMode] = useState<Mode>("later");
  const [paid, setPaid] = useState("");
  const [method, setMethod] = useState<Method>("cash");
  const [dueDays, setDueDays] = useState<(typeof DUE_DAYS)[number]>(15);
  const [creating, setCreating] = useState(false);
  // Le fournisseur créé ici reste choisi même s'il n'est pas parmi les 100 premiers.
  const [created, setCreated] = useState<{ id: string; name: string } | null>(null);
  const [search, setSearch] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const term = useDebouncedValue(search.trim());

  const suppliers = useQuery({
    queryKey: queryKeys.suppliers.list({ delivery: true }),
    queryFn: () => unwrap(api.GET("/api/v1/suppliers", { params: { query: { page_size: 100 } } })),
  });
  const watched = useQuery({
    queryKey: queryKeys.stock.list({ delivery: "low" }),
    queryFn: async () => {
      const [low, out] = await Promise.all(
        (["low", "out"] as const).map((status) =>
          unwrap(
            api.GET("/api/v1/inventory/stock", {
              params: { query: { status, page_size: 20 } },
            }),
          ),
        ),
      );
      return [...(low?.items ?? []), ...(out?.items ?? [])];
    },
  });
  const prefill = useQuery({
    queryKey: queryKeys.stock.list({ delivery: "prefill", product_id: productId }),
    enabled: Boolean(productId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/inventory/stock", {
          params: { query: { product_id: [productId!], page_size: 1 } },
        }),
      ),
  });
  const found = useQuery({
    queryKey: queryKeys.stock.list({ delivery: "search", term }),
    enabled: term.length >= 2,
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/inventory/stock", {
          params: { query: { search: term, page_size: 8 } },
        }),
      ),
  });

  // « Commander » depuis une fiche : l'article arrive déjà sur la liste (ADR 0071).
  const first = prefill.data?.items[0];
  if (!seeded && first) {
    setSeeded(true);
    setLines([{ product: first, qty: "", cost: suggestedCost(first) }]);
  }

  const add = (product: StockLine) => {
    if (lines.some((line) => line.product.product_id === product.product_id)) return;
    setLines((current) => [...current, { product, qty: "", cost: suggestedCost(product) }]);
    setSearch("");
  };
  const patch = (index: number, change: Partial<Line>) =>
    setLines((current) => current.map((line, i) => (i === index ? { ...line, ...change } : line)));

  const total = lines.reduce((sum, line) => sum + lineTotal(line), 0n);
  const paidAmount = typedAmount(paid);
  // Le fournisseur venu de sa fiche peut être au-delà des 100 premiers : on le lit à part.
  const asked = useQuery({
    queryKey: queryKeys.suppliers.detail(askedSupplierId ?? "none"),
    enabled: Boolean(askedSupplierId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/suppliers/{supplier_id}", {
          params: { path: { supplier_id: askedSupplierId! } },
        }),
      ),
  });
  const extraSuppliers = [created, asked.data ?? null].filter(
    (item): item is { id: string; name: string } =>
      item !== null && !suppliers.data?.items.some((listed) => listed.id === item.id),
  );
  const supplierChoices = [
    ...(suppliers.data?.items ?? []),
    ...extraSuppliers.filter(
      (item, index) => extraSuppliers.findIndex((o) => o.id === item.id) === index,
    ),
  ];
  const supplier = supplierChoices.find((item) => item.id === supplierId);
  const validLines = lines.filter((line) => {
    const qty = parseDecimalInput(line.qty);
    return qty !== null && compareDecimal(qty, "0") === 1 && line.cost !== "";
  });
  const partMessage =
    paidAmount === 0n
      ? t.partEmpty
      : paidAmount >= total
        ? t.partTooMuch
        : t.partRest(formatAmount((total - paidAmount).toString(), currency));
  const blocked =
    !supplier ||
    total === 0n ||
    validLines.length !== lines.length ||
    (mode === "part" && (paidAmount === 0n || paidAmount >= total));

  const save = useMutation({
    meta: { toastError: false },
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/inventory/deliveries", {
          body: {
            supplier_id: supplierId!,
            lines: lines.map((line) => ({
              product_id: line.product.product_id,
              qty: parseDecimalInput(line.qty) ?? "0",
              unit_cost: line.cost,
            })),
            payment_mode: mode,
            paid_amount: mode === "part" ? paid : null,
            method,
            due_date: mode === "now" ? null : addDays(todayIn(timeZone), dueDays),
          },
          headers: idempotency.headers,
        }),
      ),
    onSuccess: (delivery) => {
      idempotency.renew();
      for (const key of [
        queryKeys.stock.all,
        queryKeys.products.all,
        queryKeys.movements.all,
        queryKeys.debts.all,
        queryKeys.payments.all,
        queryKeys.dashboard,
      ]) {
        void queryClient.invalidateQueries({ queryKey: key });
      }
      const who = supplier?.name ?? "";
      setDone(
        mode === "now"
          ? t.donePaid(formatAmount(delivery.total, currency), who)
          : t.doneOwed(formatAmount(delivery.balance, currency), who, dueDays),
      );
    },
    onError: (failure) => setError(errorMessage(failure)),
  });

  const addable = (watched.data ?? []).filter(
    (item) => !lines.some((line) => line.product.product_id === item.product_id),
  );

  return (
    <div className="mx-auto flex max-w-page flex-col gap-5">
      <h1 className="text-titre-page leading-[1.45] tracking-[-0.01em]">{t.title}</h1>

      {done ? (
        <section
          aria-live="polite"
          className="flex flex-col items-center gap-2.5 rounded-carte border border-border bg-card px-6 py-9 text-center"
        >
          <span
            aria-hidden
            className="flex size-20 items-center justify-center rounded-full bg-stock text-primary-foreground"
          >
            <Check className="size-11" strokeWidth={2.5} />
          </span>
          <h2 className="text-[26px] leading-tight font-extrabold">{t.done}</h2>
          <p className="text-lg font-semibold">{done}</p>
          <p className="text-[17px] text-muted-foreground">{t.doneStock}</p>
          <Link
            href="/products"
            className="mt-2 inline-flex min-h-bouton items-center rounded-bouton bg-stock px-5 text-[17px] font-bold text-primary-foreground outline-none hover:bg-stock/90 focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            {t.seeStock}
          </Link>
        </section>
      ) : (
        <div className="flex flex-wrap items-start gap-5">
          <section className="min-w-0 flex-[3_1_500px] rounded-carte border border-border bg-card p-carte">
            <p id="who" className="mb-2.5 text-libelle">
              {t.who}
            </p>
            {suppliers.isPending ? (
              <Skeleton className="h-12 w-full" />
            ) : (
              <div role="group" aria-labelledby="who" className="flex flex-wrap gap-2">
                {supplierChoices.map((item) => (
                  <Chip
                    key={item.id}
                    rubrique="stock"
                    className="min-h-[52px]"
                    selected={supplierId === item.id}
                    onClick={() => setSupplierId(item.id)}
                  >
                    {item.name}
                  </Chip>
                ))}
                <Chip
                  rubrique="stock"
                  className="min-h-[52px] border-dashed"
                  onClick={() => setCreating(true)}
                >
                  {t.newSupplier}
                </Chip>
              </div>
            )}

            <p className="mt-[22px] mb-2.5 text-libelle">{t.what}</p>
            {lines.length === 0 && (
              <p className="border-t border-filet py-3.5 text-muted-foreground">{t.noLine}</p>
            )}
            {lines.map((line, index) => {
              const name = line.product.name;
              const stockText =
                line.product.status === "out"
                  ? t.outOfStock
                  : qtyWithUnit(line.product.qty_on_hand, line.product.unit);
              return (
                <div
                  key={line.product.product_id}
                  className="flex flex-wrap items-end gap-3 border-t border-filet py-3.5"
                >
                  <ProductSquare name={name} />
                  <div className="min-w-0 flex-[1_1_170px] self-center">
                    <p className="font-bold">{name}</p>
                    <p className="text-muted-foreground">{t.inStock(stockText)}</p>
                  </div>
                  <label className="w-[110px]">
                    <span className="mb-1 block text-petit font-semibold text-muted-foreground">
                      {t.qty}
                    </span>
                    <input
                      inputMode="decimal"
                      autoComplete="off"
                      aria-label={`${t.qty} : ${name}`}
                      value={line.qty}
                      onChange={(event) => patch(index, { qty: cleanQuantity(event.target.value) })}
                      className={cn(
                        fieldClasses("stock"),
                        "min-h-[52px] rounded-touche px-3 text-[19px] font-bold numeric",
                      )}
                    />
                  </label>
                  <label className="w-[150px]">
                    <span className="mb-1 block text-petit font-semibold text-muted-foreground">
                      {t.cost}
                    </span>
                    <input
                      inputMode="numeric"
                      autoComplete="off"
                      aria-label={`${t.cost} : ${name}`}
                      value={line.cost}
                      onChange={(event) => patch(index, { cost: cleanAmount(event.target.value) })}
                      className={cn(
                        fieldClasses("stock"),
                        "min-h-[52px] rounded-touche px-3 text-[19px] font-bold numeric",
                      )}
                    />
                  </label>
                  <span className="w-[110px] self-center text-right text-lg font-extrabold numeric">
                    {formatAmount(lineTotal(line).toString(), currency)}
                  </span>
                  <button
                    type="button"
                    aria-label={t.remove(name)}
                    onClick={() => setLines((current) => current.filter((_, i) => i !== index))}
                    className="flex size-12 items-center justify-center rounded-touche border-2 border-input bg-card text-depenses-encre outline-none hover:bg-voile focus-visible:ring-3 focus-visible:ring-ring/50"
                  >
                    <X className="size-[22px]" aria-hidden />
                  </button>
                </div>
              );
            })}
            <p className="mt-3 font-bold">{t.add}</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {addable.map((item) => (
                <Chip
                  key={item.product_id}
                  rubrique="stock"
                  className="min-h-[52px]"
                  onClick={() => add(item)}
                >
                  {t.addOne(item.name)}
                </Chip>
              ))}
            </div>
            <div className="relative mt-3">
              <Search
                className="pointer-events-none absolute top-[15px] left-4 size-5 text-muted-foreground"
                aria-hidden
              />
              <input
                type="search"
                aria-label={t.search}
                placeholder={t.search}
                autoComplete="off"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                className={cn(fieldClasses("stock"), "min-h-[52px] pr-4 pl-12 text-corps")}
              />
            </div>
            {term.length >= 2 && (found.data?.items.length ?? 0) > 0 && (
              <div className="mt-2 flex flex-wrap gap-2">
                {found.data?.items
                  .filter(
                    (item) =>
                      item.is_stock_tracked &&
                      !lines.some((line) => line.product.product_id === item.product_id),
                  )
                  .map((item) => (
                    <Chip
                      key={item.product_id}
                      rubrique="stock"
                      className="min-h-[52px]"
                      onClick={() => add(item)}
                    >
                      {t.addOne(item.name)}
                    </Chip>
                  ))}
              </div>
            )}
          </section>

          <section className="flex min-w-0 flex-[2_1_340px] flex-col gap-4 rounded-carte border border-border bg-card p-carte">
            <div className="flex items-baseline justify-between rounded-champ bg-stock-teinte px-4 py-3.5">
              <span className="text-lg font-bold">{t.total}</span>
              <span className="text-[30px] leading-tight font-extrabold numeric text-stock-encre">
                {formatAmount(total.toString(), currency)}
              </span>
            </div>
            <p id="pay" className="text-libelle">
              {t.pay}
            </p>
            <div role="group" aria-labelledby="pay" className="flex flex-wrap gap-2">
              {MODES.map((value) => (
                <button
                  key={value}
                  type="button"
                  aria-pressed={mode === value}
                  onClick={() => {
                    setMode(value);
                    setPaid("");
                  }}
                  className={cn(
                    "min-h-[60px] flex-[1_1_140px] rounded-[18px] border-2 text-[17px] font-bold",
                    "outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                    mode === value
                      ? "border-stock bg-stock text-primary-foreground"
                      : "border-input bg-card text-foreground hover:bg-voile",
                  )}
                >
                  {t.modes[value]}
                </button>
              ))}
            </div>
            {mode === "part" && (
              <div>
                <label htmlFor="delivery-paid" className="mb-2.5 block text-libelle">
                  {t.givesNow}
                </label>
                <input
                  id="delivery-paid"
                  inputMode="numeric"
                  autoComplete="off"
                  placeholder={t.typeAmount}
                  value={paid}
                  onChange={(event) => setPaid(cleanAmount(event.target.value))}
                  className={cn(
                    fieldClasses("stock"),
                    "min-h-[60px] rounded-touche px-3 text-2xl font-bold numeric",
                  )}
                />
                <p role="status" className="mt-2 font-bold text-stock-encre">
                  {partMessage}
                </p>
              </div>
            )}
            {mode !== "later" && (
              <div role="group" aria-label={t.methods} className="flex flex-wrap gap-2">
                {METHODS.map((value) => (
                  <Chip
                    key={value}
                    rubrique="stock"
                    className="min-h-[52px] flex-[1_1_110px]"
                    selected={method === value}
                    onClick={() => setMethod(value)}
                  >
                    {labels.paymentMethods[value]}
                  </Chip>
                ))}
              </div>
            )}
            {mode !== "now" && (
              <div>
                <p id="due" className="mb-2.5 text-libelle">
                  {t.dueTitle}
                </p>
                <div role="group" aria-labelledby="due" className="flex flex-wrap gap-2">
                  {DUE_DAYS.map((days) => (
                    <Chip
                      key={days}
                      rubrique="stock"
                      className="min-h-[52px] flex-[1_1_110px]"
                      selected={dueDays === days}
                      onClick={() => setDueDays(days)}
                    >
                      {t.due(days)}
                    </Chip>
                  ))}
                </div>
              </div>
            )}
            {!supplier && lines.length > 0 && (
              <p className="rounded-champ bg-stock-teinte px-4 py-3 font-bold text-stock-encre">
                {t.pickSupplier}
              </p>
            )}
            <FieldError message={error} />
            <button
              type="button"
              disabled={blocked || save.isPending}
              onClick={() => {
                setError(null);
                save.mutate();
              }}
              className={cn(
                "min-h-bouton-principal w-full rounded-bouton bg-stock text-xl font-bold text-primary-foreground",
                "outline-none hover:bg-stock/90 focus-visible:ring-3 focus-visible:ring-ring/50",
                "disabled:cursor-not-allowed disabled:bg-stock/45",
              )}
            >
              {t.submit}
            </button>
          </section>
        </div>
      )}
      <PersonFormDialog
        kind="supplier"
        open={creating}
        onOpenChange={setCreating}
        onSaved={(saved) => {
          void queryClient.invalidateQueries({ queryKey: queryKeys.suppliers.all });
          setCreated({ id: saved.person.id, name: saved.person.name });
          setSupplierId(saved.person.id);
        }}
      />
    </div>
  );
}
