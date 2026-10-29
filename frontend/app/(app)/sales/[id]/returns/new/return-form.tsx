"use client";

import { useIsMutating, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { DraftBanner } from "@/components/draft-banner";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { FieldError } from "@/components/field-error";
import { AmountField } from "@/components/kit/amount-field";
import { Chip } from "@/components/kit/chip";
import { ProductSquare } from "@/components/kit/list-row";
import { cleanQuantity } from "@/components/kit/quantity-stepper";
import { fieldClasses } from "@/components/kit/rubrique";
import { Skeleton } from "@/components/ui/skeleton";
import { useDraft } from "@/hooks/use-draft";
import { useCompanyLocale } from "@/hooks/use-me";
import { usePermission } from "@/hooks/use-permission";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import { useIdempotencyKey } from "@/lib/api/idempotency";
import { queryKeys } from "@/lib/api/queries/keys";
import { compareDecimal, parseDecimalInput, subtractDecimal, toInputDecimal } from "@/lib/decimal";
import { draftOneOf, draftString } from "@/lib/drafts";
import { formatAmount, formatClock, formatDate, formatQty } from "@/lib/format";
import { labels } from "@/lib/labels";
import { typedAmount, wholeUnits } from "@/lib/payment-amount";
import { addDays, todayIn } from "@/lib/period";
import { centsToAmount, refundCents } from "@/lib/refund";
import { displayNumber } from "@/lib/units";
import { cn } from "@/lib/utils";

type Way = "cash" | "later";
type Method = "cash" | "wave" | "orange_money";
type Done = { returnId: string; line: string };

const t = labels.returns.form;
const METHODS: readonly Method[] = ["cash", "wave", "orange_money"];

/** Brouillon d'un retour (ADR 0101), un par vente ; ses deux clés d'idempotence voyagent avec lui. */
const DRAFT = {
  formId: "sale-return",
  version: 1,
  fields: ["quantities", "reason", "way", "refundTyped", "method", "createIdem", "refundIdem"],
  meaningful: ["quantities"],
  keys: ["createIdem", "refundIdem"],
} as const;
const SAVE_KEY = ["sale-return", "save"];

const STEP = cn(
  "flex size-[52px] shrink-0 items-center justify-center rounded-touche border-2 border-input bg-card text-2xl font-bold text-foreground",
  "outline-none hover:bg-voile focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50",
);

/**
 * Retour d'articles, maquette v2 (écran 06), en un seul écran : ce qu'il rend (libre,
 * plafonné à ce qui reste retournable), pourquoi, la valeur rendue, et que faire de cet
 * argent. La dette restante de la vente est déduite d'abord, par le serveur, dans la
 * transaction du retour (`offset_debt`, ADR 0097) ; le reste se rend maintenant ou plus
 * tard, par qui a le droit de rembourser (`sale_returns:confirm`). Pour les autres, le
 * retour s'enregistre et le gérant rembourse ensuite. Le retour et son remboursement
 * partent en deux écritures, chacune sous sa clé d'idempotence : si le remboursement
 * échoue, l'écran dit pourquoi et le retour reste à régler depuis sa fiche.
 */
export function ReturnForm({ saleId }: { saleId: string }) {
  const queryClient = useQueryClient();
  const { currency, timeZone } = useCompanyLocale();
  const canRefund = usePermission("sale_returns:confirm");
  const createKey = useIdempotencyKey();
  const refundKey = useIdempotencyKey();
  const [quantities, setQuantities] = useState<Record<string, string>>({});
  const [reason, setReason] = useState<string>(t.reasons[0]);
  const [way, setWay] = useState<Way | null>(null);
  const [refundTyped, setRefundTyped] = useState<string | null>(null);
  const [method, setMethod] = useState<Method>("cash");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<Done | null>(null);
  // Tout l'envoi (retour puis remboursement), puis l'écran « enregistré » : rien n'est réécrit.
  const saving = useIsMutating({ mutationKey: SAVE_KEY }) > 0;
  const draft = useDraft(
    { ...DRAFT, objectId: saleId, busy: saving || done !== null },
    {
      // Seules les lignes remplies : une ligne remise à zéro n'est pas une saisie.
      quantities: Object.fromEntries(Object.entries(quantities).filter(([, qty]) => qty !== "")),
      reason,
      way: way ?? "",
      refundTyped: refundTyped ?? "",
      method,
      createIdem: createKey.key,
      refundIdem: refundKey.key,
    },
    (fields) => {
      const saved = fields.quantities;
      if (saved && typeof saved === "object") {
        setQuantities(
          Object.fromEntries(
            Object.entries(saved as Record<string, unknown>).filter(
              (entry): entry is [string, string] => typeof entry[1] === "string",
            ),
          ),
        );
      }
      setReason(draftOneOf(fields.reason, t.reasons) ?? t.reasons[0]);
      setWay(draftOneOf(fields.way, ["cash", "later"] as const) ?? null);
      const typed = draftString(fields.refundTyped);
      setRefundTyped(typed ? typed : null);
      setMethod(draftOneOf(fields.method, METHODS) ?? "cash");
      createKey.restore(fields.createIdem);
      refundKey.restore(fields.refundIdem);
    },
  );

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
  const chosen: Way = way ?? "cash";

  const rows = (data?.items ?? []).map((item) => ({
    item,
    returnable: subtractDecimal(item.qty, item.returned_qty) ?? "0",
  }));
  // Un brouillon retrouvé ne rend jamais plus que ce qui reste à retourner aujourd'hui : un
  // autre retour a pu passer entre-temps (le serveur revérifie de toute façon, CG040).
  const qtyOf = (id: string) => {
    const typed = parseDecimalInput(quantities[id] ?? "") ?? "0";
    const left = rows.find((row) => row.item.id === id)?.returnable;
    return left !== undefined && compareDecimal(typed, left) === 1 ? left : typed;
  };
  const valueCents = rows.reduce((sum, { item }) => sum + refundCents(item, qtyOf(item.id)), 0n);
  const value = wholeUnits(centsToAmount(valueCents));
  // Ce qui est déduit de la dette d'abord, puis ce qui reste à lui rendre.
  const deducted = min(value, debtBalance);
  const rest = value - deducted;
  const paysNow = canRefund && rest > 0n && chosen === "cash";
  const refund = refundTyped === null ? rest : typedAmount(refundTyped);
  const money = (amount: bigint) => formatAmount(amount.toString(), currency);

  let message = "";
  if (value === 0n) message = t.nothing;
  else if (paysNow && refund > rest) message = t.tooMuch(money(rest));
  const blocked = value === 0n || (paysNow && (refund <= 0n || refund > rest));

  const save = useMutation({
    mutationKey: SAVE_KEY,
    meta: { toastError: false },
    mutationFn: async () => {
      const lines = rows
        .map(({ item }) => ({ sale_item_id: item.id, qty: qtyOf(item.id) }))
        .filter((line) => compareDecimal(line.qty, "0") === 1);
      const created = await unwrap(
        api.POST("/api/v1/sales/{sale_id}/returns", {
          params: { path: { sale_id: saleId } },
          body: { lines, reason, offset_debt: true },
          headers: createKey.headers,
        }),
      );
      // Le serveur a déjà déduit la dette : `refund_due` est ce qui reste à rendre.
      const due = wholeUnits(created.refund_due);
      const amount = paysNow ? min(due, refund) : 0n;
      let failure: string | null = null;
      if (amount > 0n) {
        try {
          await unwrap(
            api.POST("/api/v1/sale-returns/{return_id}/refunds", {
              params: { path: { return_id: created.id } },
              body: { amount: amount.toString(), method },
              headers: refundKey.headers,
            }),
          );
        } catch (refused) {
          failure = errorMessage(refused);
        }
      }
      return { created, amount, failure };
    },
    onSuccess: ({ created, amount, failure }) => {
      // Les clés ne changent qu'une fois tout l'envoi fini et le brouillon effacé (R1, prompt
      // 32) : une page morte en route rejoue avec les mêmes. Un remboursement refusé repart
      // de la fiche du retour, sous une clé à lui.
      draft.clear();
      createKey.renew();
      refundKey.renew();
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
      const parts: string[] = [];
      if (deducted > 0n) parts.push(t.doneDebt(name, money(debtBalance - deducted)));
      if (failure !== null) parts.push(t.settleFailed(money(amount), failure));
      else if (amount > 0n) parts.push(t.doneCash(money(amount), name));
      const left = failure !== null ? owed : owed - amount;
      if (left > 0n && failure === null) {
        parts.push(canRefund ? t.doneLater(money(left), name) : t.doneManager(money(left)));
      }
      setDone({ returnId: created.id, line: parts.join(". ") });
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
            {draft.restored && (
              <div className="mb-3">
                <DraftBanner
                  onClear={() => {
                    setQuantities({});
                    setReason(t.reasons[0]);
                    setWay(null);
                    setRefundTyped(null);
                    setMethod("cash");
                    draft.clear();
                  }}
                />
              </div>
            )}
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
            {debtBalance > 0n && value > 0n && (
              <p className="rounded-champ bg-clients-teinte px-4 py-3 font-bold text-clients-encre">
                {t.debtFirst(money(debtBalance), money(deducted))}
              </p>
            )}
            {rest > 0n && deducted > 0n && <p className="text-libelle">{t.rest(money(rest))}</p>}
            {rest > 0n && !canRefund && (
              <p role="note" className="rounded-champ bg-voile px-4 py-3 font-bold">
                {t.managerRefunds(money(rest))}
              </p>
            )}
            {rest > 0n && canRefund && (
              <>
                <p id="return-money" className="text-libelle">
                  {t.money}
                </p>
                <div role="group" aria-labelledby="return-money" className="flex flex-col gap-2">
                  {(["cash", "later"] as const).map((option) => (
                    <button
                      key={option}
                      type="button"
                      aria-pressed={chosen === option}
                      onClick={() => {
                        setWay(option);
                        setRefundTyped(null);
                      }}
                      className={cn(
                        "flex min-h-[76px] flex-[1_1_230px] items-center rounded-[18px] border-2 px-4 py-3 text-left text-[17px] font-bold",
                        "outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                        chosen === option
                          ? "border-argent bg-argent-teinte text-argent-encre"
                          : "border-input bg-card text-foreground hover:bg-voile",
                      )}
                    >
                      <span className="flex-1">
                        {t.ways[option]}
                        <span className="block text-sm font-medium text-muted-foreground">
                          {t.waysHint[option]}
                        </span>
                      </span>
                    </button>
                  ))}
                </div>
              </>
            )}

            {paysNow && (
              <div className="flex flex-col gap-2.5">
                <AmountField
                  label={t.howMuch}
                  placeholder={t.typeAmount}
                  rubrique="argent"
                  value={refundTyped ?? rest.toString()}
                  onChange={setRefundTyped}
                  invalid={refund > rest}
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
