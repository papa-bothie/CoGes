"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { FieldError } from "@/components/field-error";
import { AmountField } from "@/components/kit/amount-field";
import { Chip } from "@/components/kit/chip";
import { ProductSquare } from "@/components/kit/list-row";
import { cleanQuantity } from "@/components/kit/quantity-stepper";
import { fieldClasses } from "@/components/kit/rubrique";
import { Skeleton } from "@/components/ui/skeleton";
import { useCompanyLocale } from "@/hooks/use-me";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import { useIdempotencyKey } from "@/lib/api/idempotency";
import { queryKeys } from "@/lib/api/queries/keys";
import { compareDecimal, parseDecimalInput, subtractDecimal, toInputDecimal } from "@/lib/decimal";
import { formatAmount, formatClock, formatDate, formatQty } from "@/lib/format";
import { labels } from "@/lib/labels";
import { typedAmount, wholeUnits } from "@/lib/payment-amount";
import { addDays, todayIn } from "@/lib/period";
import { centsToAmount, refundCents } from "@/lib/refund";
import { displayNumber } from "@/lib/units";
import { cn } from "@/lib/utils";

type Way = "debt" | "cash" | "later";
type Method = "cash" | "wave" | "orange_money";
type Done = { returnId: string; line: string };

const t = labels.returns.form;
const METHODS: readonly Method[] = ["cash", "wave", "orange_money"];

const STEP = cn(
  "flex size-[52px] shrink-0 items-center justify-center rounded-touche border-2 border-input bg-card text-2xl font-bold text-foreground",
  "outline-none hover:bg-voile focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50",
);

/**
 * Retour d'articles, maquette v2 (écran 06), en un seul écran : ce qu'il rend (libre,
 * plafonné à ce qui reste retournable), pourquoi, la valeur rendue, et que faire de cet
 * argent — déduire de sa dette (compensation, ADR 0024), lui rendre maintenant, ou plus
 * tard. Le retour et son règlement partent en deux écritures, chacune sous sa clé
 * d'idempotence : si le règlement échoue, le retour reste à régler depuis sa fiche.
 */
export function ReturnForm({ saleId }: { saleId: string }) {
  const queryClient = useQueryClient();
  const { currency, timeZone } = useCompanyLocale();
  const createKey = useIdempotencyKey();
  const refundKey = useIdempotencyKey();
  const [quantities, setQuantities] = useState<Record<string, string>>({});
  const [reason, setReason] = useState<string>(t.reasons[0]);
  const [way, setWay] = useState<Way | null>(null);
  const [refundTyped, setRefundTyped] = useState<string | null>(null);
  const [method, setMethod] = useState<Method>("cash");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<Done | null>(null);

  const sale = useQuery({
    queryKey: queryKeys.sales.detail(saleId),
    queryFn: () =>
      unwrap(api.GET("/api/v1/sales/{sale_id}", { params: { path: { sale_id: saleId } } })),
  });
  const data = sale.data;

  const debt = data?.debt;
  const debtBalance =
    debt && (debt.status === "open" || debt.status === "partially_paid")
      ? wholeUnits(debt.balance)
      : 0n;
  const canOffset = debtBalance > 0n;
  const chosen: Way = way ?? (canOffset ? "debt" : "cash");

  const rows = (data?.items ?? []).map((item) => ({
    item,
    returnable: subtractDecimal(item.qty, item.returned_qty) ?? "0",
  }));
  const qtyOf = (id: string) => parseDecimalInput(quantities[id] ?? "") ?? "0";
  const valueCents = rows.reduce((sum, { item }) => sum + refundCents(item, qtyOf(item.id)), 0n);
  const value = wholeUnits(centsToAmount(valueCents));
  const refund = refundTyped === null ? value : typedAmount(refundTyped);
  const money = (amount: bigint) => formatAmount(amount.toString(), currency);

  let message = "";
  if (value === 0n) message = t.nothing;
  else if (chosen === "cash" && refund > value) message = t.tooMuch(money(value));
  else if (chosen === "debt" && value > debtBalance)
    message = t.debtCleared(money(value - debtBalance));
  const blocked = value === 0n || (chosen === "cash" && (refund <= 0n || refund > value));

  const save = useMutation({
    meta: { toastError: false },
    mutationFn: async () => {
      const lines = rows
        .map(({ item }) => ({ sale_item_id: item.id, qty: qtyOf(item.id) }))
        .filter((line) => compareDecimal(line.qty, "0") === 1);
      const created = await unwrap(
        api.POST("/api/v1/sales/{sale_id}/returns", {
          params: { path: { sale_id: saleId } },
          body: { lines, reason },
          headers: createKey.headers,
        }),
      );
      createKey.renew();
      const due = wholeUnits(created.refund_due);
      const amount = chosen === "debt" ? min(due, debtBalance) : min(due, refund);
      let settled = true;
      if (chosen !== "later" && amount > 0n) {
        try {
          await unwrap(
            api.POST("/api/v1/sale-returns/{return_id}/refunds", {
              params: { path: { return_id: created.id } },
              body: { amount: amount.toString(), method: chosen === "debt" ? "offset" : method },
              headers: refundKey.headers,
            }),
          );
          refundKey.renew();
        } catch {
          settled = false;
        }
      }
      return { created, amount, settled };
    },
    onSuccess: ({ created, amount, settled }) => {
      for (const key of [
        queryKeys.sales.all,
        queryKeys.stock.all,
        queryKeys.dashboard,
        queryKeys.saleReturns.all,
        queryKeys.debts.all,
        queryKeys.payments.all,
      ]) {
        void queryClient.invalidateQueries({ queryKey: key });
      }
      const name = data?.customer_name ?? labels.sales.anonymous;
      const owed = wholeUnits(created.refund_due);
      const line = !settled
        ? t.settleFailed
        : chosen === "debt"
          ? t.doneDebt(name, money(debtBalance - amount))
          : chosen === "cash"
            ? t.doneCash(money(amount), name)
            : t.doneLater(money(owed), name);
      setDone({ returnId: created.id, line });
    },
    onError: (failure) => setError(errorMessage(failure)),
  });

  if (sale.isError) return <ErrorState error={sale.error} onRetry={() => void sale.refetch()} />;
  if (!data) return <Skeleton className="mx-auto h-96 max-w-page" />;

  const today = todayIn(timeZone);
  const day = todayIn(timeZone, new Date(data.sold_at));
  const time = formatClock(data.sold_at, timeZone);
  const when =
    day === today
      ? t.today(time)
      : day === addDays(today, -1)
        ? t.yesterday(time)
        : t.onDay(formatDate(data.sold_at, timeZone), time);
  const anyReturnable = rows.some(({ returnable }) => compareDecimal(returnable, "0") === 1);

  const setQty = (id: string, raw: string, max: string) => {
    const cleaned = cleanQuantity(raw);
    const parsed = parseDecimalInput(cleaned);
    const capped = parsed && compareDecimal(parsed, max) === 1 ? toInputDecimal(max) : cleaned;
    setQuantities((current) => ({ ...current, [id]: capped === "0" ? "" : capped }));
    setRefundTyped(null);
  };
  const step = (id: string, delta: 1 | -1, max: string) => {
    const next = wholeUnits(qtyOf(id)) + BigInt(delta);
    setQty(id, next <= 0n ? "" : next.toString(), max);
  };

  return (
    <div className="mx-auto flex max-w-page flex-col gap-5">
      <Link
        href={`/sales/${saleId}`}
        className="inline-flex min-h-11 items-center gap-2 self-start font-bold text-ventes hover:text-ventes-encre pointer-coarse:min-h-12"
      >
        <ArrowLeft className="size-[22px]" aria-hidden />
        {t.back(displayNumber(data.sale_no))}
      </Link>
      <div>
        <h1 className="text-titre-page leading-[1.45] tracking-[-0.01em]">{t.title}</h1>
        <p className="text-lg text-muted-foreground">
          {t.subtitle(data.customer_name ?? labels.sales.anonymous, when)}
        </p>
      </div>

      {done ? (
        <section className="flex flex-col items-center gap-2.5 rounded-carte border border-border bg-card px-6 py-9 text-center">
          <span
            aria-hidden
            className="flex size-20 items-center justify-center rounded-full bg-argent text-primary-foreground"
          >
            <Check className="size-11" strokeWidth={2.5} />
          </span>
          <h2 className="text-[26px] leading-tight font-extrabold">{t.done}</h2>
          <p role="status" className="text-lg font-semibold">
            {done.line}
          </p>
          <p className="text-[17px] text-muted-foreground">{t.doneStock}</p>
          <div className="mt-2 flex flex-wrap justify-center gap-2.5">
            <Link
              href={`/sales/returns/${done.returnId}/receipt`}
              className="inline-flex min-h-bouton items-center rounded-bouton bg-argent px-5 text-[17px] font-bold text-primary-foreground outline-none hover:bg-argent/90 focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              {t.printSlip}
            </Link>
            <Link
              href="/sales"
              className="inline-flex min-h-bouton items-center rounded-bouton border-2 border-input bg-card px-5 text-[17px] font-bold text-foreground outline-none hover:bg-voile focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              {t.backToSales}
            </Link>
          </div>
        </section>
      ) : !anyReturnable ? (
        <EmptyState title={labels.returns.nothingReturnable} />
      ) : (
        <div className="flex flex-wrap items-start gap-5">
          <section className="min-w-0 flex-[3_1_480px] rounded-carte border border-border bg-card p-carte">
            <p className="mb-2.5 text-libelle">{t.what}</p>
            {rows.map(({ item, returnable }) => {
              const name = item.product_name ?? labels.sales.deletedProduct;
              const none = compareDecimal(returnable, "0") !== 1;
              return (
                <div
                  key={item.id}
                  className="flex flex-wrap items-center gap-3 border-t border-filet py-3.5"
                >
                  <ProductSquare name={name} />
                  <div className="min-w-0 flex-[1_1_160px]">
                    <p className="font-bold">{name}</p>
                    <p className="numeric text-muted-foreground">
                      {t.bought(formatQty(item.qty), formatAmount(item.unit_price, currency))}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      className={STEP}
                      disabled={none}
                      onClick={() => step(item.id, -1, returnable)}
                      aria-label={`${t.oneLess} : ${name}`}
                    >
                      <span aria-hidden>−</span>
                    </button>
                    <input
                      inputMode="decimal"
                      autoComplete="off"
                      aria-label={t.qtyLabel(name)}
                      value={quantities[item.id] ?? ""}
                      disabled={none}
                      onChange={(event) => setQty(item.id, event.target.value, returnable)}
                      className={cn(
                        fieldClasses("argent"),
                        "h-[52px] w-[72px] rounded-touche text-center text-[22px] font-extrabold numeric",
                      )}
                    />
                    <button
                      type="button"
                      className={STEP}
                      disabled={none}
                      onClick={() => step(item.id, 1, returnable)}
                      aria-label={`${t.oneMore} : ${name}`}
                    >
                      <span aria-hidden>+</span>
                    </button>
                  </div>
                </div>
              );
            })}
            <p id="return-why" className="mt-[18px] mb-2.5 text-libelle">
              {t.why}
            </p>
            <div role="group" aria-labelledby="return-why" className="flex flex-wrap gap-2">
              {t.reasons.map((label) => (
                <Chip
                  key={label}
                  rubrique="argent"
                  className="min-h-[52px]"
                  selected={reason === label}
                  onClick={() => setReason(label)}
                >
                  {label}
                </Chip>
              ))}
            </div>
          </section>

          <section className="flex min-w-0 flex-[2_1_360px] flex-col gap-4 rounded-carte border border-border bg-card p-carte">
            <div className="flex items-baseline justify-between rounded-champ bg-argent-teinte px-4 py-3.5">
              <span className="text-lg font-bold">{t.value}</span>
              <span
                aria-live="polite"
                className="text-[30px] leading-tight font-extrabold numeric text-argent-encre"
              >
                {money(value)}
              </span>
            </div>
            <p id="return-money" className="text-libelle">
              {t.money}
            </p>
            <div role="group" aria-labelledby="return-money" className="flex flex-col gap-2">
              {(["debt", "cash", "later"] as const).map((option) => {
                const hint =
                  option === "debt"
                    ? canOffset
                      ? t.waysHint.debt(money(debtBalance))
                      : t.waysHint.noDebt
                    : t.waysHint[option];
                return (
                  <button
                    key={option}
                    type="button"
                    aria-pressed={chosen === option}
                    disabled={option === "debt" && !canOffset}
                    onClick={() => {
                      setWay(option);
                      setRefundTyped(null);
                    }}
                    className={cn(
                      "flex min-h-[76px] flex-[1_1_230px] items-center rounded-[18px] border-2 px-4 py-3 text-left text-[17px] font-bold",
                      "outline-none focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50",
                      chosen === option
                        ? "border-argent bg-argent-teinte text-argent-encre"
                        : "border-input bg-card text-foreground hover:bg-voile",
                    )}
                  >
                    <span className="flex-1">
                      {t.ways[option]}
                      <span className="block text-sm font-medium text-muted-foreground">
                        {hint}
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>

            {chosen === "cash" && (
              <div className="flex flex-col gap-2.5">
                <AmountField
                  label={t.howMuch}
                  placeholder={t.typeAmount}
                  rubrique="argent"
                  value={refundTyped ?? (value > 0n ? value.toString() : "")}
                  onChange={setRefundTyped}
                  invalid={refund > value}
                />
                <div role="group" aria-label={t.methods} className="flex flex-wrap gap-2">
                  {METHODS.map((value) => (
                    <Chip
                      key={value}
                      rubrique="argent"
                      className="flex-[1_1_110px]"
                      selected={method === value}
                      onClick={() => setMethod(value)}
                    >
                      {labels.paymentMethods[value]}
                    </Chip>
                  ))}
                </div>
              </div>
            )}

            {message && (
              <p className="rounded-champ bg-stock-teinte px-4 py-3 font-bold text-stock-encre">
                {message}
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
                "min-h-bouton-principal w-full rounded-bouton bg-argent text-xl font-bold text-primary-foreground",
                "outline-none hover:bg-argent/90 focus-visible:ring-3 focus-visible:ring-ring/50",
                "disabled:cursor-not-allowed disabled:bg-argent/45",
              )}
            >
              {t.submit}
            </button>
          </section>
        </div>
      )}
    </div>
  );
}

function min(a: bigint, b: bigint): bigint {
  return a < b ? a : b;
}
