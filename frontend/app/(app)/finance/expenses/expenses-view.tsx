"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Loader2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { ErrorState } from "@/components/error-state";
import { FieldError } from "@/components/field-error";
import { AmountField, NumericPad } from "@/components/kit/amount-field";
import { ChoiceTiles } from "@/components/kit/choice-tile";
import { KitCard } from "@/components/kit/kit-card";
import { PaymentMethodChips } from "@/components/kit/payment-method-chips";
import { TODAY, WhenChips, whenDay, type When } from "@/components/kit/when-chips";
import { Skeleton } from "@/components/ui/skeleton";
import { useCompanyLocale } from "@/hooks/use-me";
import { Can, usePermission } from "@/hooks/use-permission";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import { useIdempotencyKey } from "@/lib/api/idempotency";
import { MONEY_KEYS, queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { expenseIcon } from "@/lib/expense-icons";
import { formatAmount, formatDayMonth } from "@/lib/format";
import { zonedDateTimeIso } from "@/lib/format/zoned";
import { labels } from "@/lib/labels";
import { MINUS } from "@/lib/money";
import { typedAmount, wholeUnits } from "@/lib/payment-amount";
import { addDays, todayIn } from "@/lib/period";
import { cn } from "@/lib/utils";

import { ExpenseCategoriesDialog } from "../expense-categories-dialog";

type Method = Schemas["PaymentMethod"];
const t = labels.moneyScreens.expensesScreen;

/** « Aujourd'hui », « Hier », sinon « 3 octobre ». */
function dayText(day: string, today: string): string {
  if (day === today) return labels.payment.today;
  if (day === addDays(today, -1)) return labels.payment.yesterday;
  return formatDayMonth(day);
}

/**
 * Dépenses, maquette v2 (écran 20) : à gauche « Nouvelle dépense » (pour quoi, combien,
 * quand, payé avec) ; à droite ce mois-ci par type et les dernières dépenses. Le libellé est
 * le nom du type : rien à écrire. Le décaissement part dans la même transaction, sous la
 * même clé d'idempotence (ADR 0053).
 */
export function ExpensesView() {
  const queryClient = useQueryClient();
  const { currency, timeZone } = useCompanyLocale();
  const canPay = usePermission("payments:create");
  const idempotency = useIdempotencyKey();
  const [categoryId, setCategoryId] = useState<string | undefined>(undefined);
  const [amount, setAmount] = useState("");
  const [when, setWhen] = useState<When>(TODAY);
  const [method, setMethod] = useState<Method>("cash");
  const [done, setDone] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [managing, setManaging] = useState(false);
  const today = todayIn(timeZone);

  const categories = useQuery({
    queryKey: queryKeys.expenseCategories.all,
    queryFn: () =>
      unwrap(api.GET("/api/v1/expense-categories", { params: { query: { page_size: 100 } } })),
  });
  const summary = useQuery({
    queryKey: queryKeys.analytics.expenses,
    queryFn: () => unwrap(api.GET("/api/v1/analytics/expenses-summary")),
  });

  const create = useMutation({
    meta: { toastError: false },
    mutationFn: (body: Schemas["ExpenseCreate"]) =>
      unwrap(api.POST("/api/v1/expenses", { body, headers: idempotency.headers })),
    onSuccess: (_data, body) => {
      idempotency.renew();
      for (const key of MONEY_KEYS) void queryClient.invalidateQueries({ queryKey: key });
      setDone(t.done(body.label, formatAmount(String(body.amount), currency)));
      setAmount("");
    },
    onError: (error) => setFormError(errorMessage(error)),
  });

  // Dans l'ordre où la boutique les a créés (maquette 20 : Loyer, Électricité, Eau…).
  const items = [...(categories.data?.items ?? [])].sort(
    (a, b) => a.created_at.localeCompare(b.created_at) || a.name.localeCompare(b.name, "fr"),
  );
  const category = items.find((item) => item.id === categoryId);
  const ready = Boolean(category) && typedAmount(amount) > 0n && !create.isPending;

  const submit = () => {
    if (!category || !ready) return;
    const day = whenDay(when, timeZone);
    setFormError(null);
    setDone(null);
    create.mutate({
      category_id: category.id,
      label: category.name,
      amount,
      spent_at: day,
      // Payée hier ou un autre jour : la sortie de caisse est datée de ce jour-là, à midi.
      payment: canPay
        ? { method, paid_at: day === today ? null : zonedDateTimeIso(`${day}T12:00`, timeZone) }
        : null,
    });
  };

  if (categories.isError) {
    return <ErrorState error={categories.error} onRetry={() => void categories.refetch()} />;
  }

  return (
    <div className="mx-auto flex max-w-page flex-col gap-5">
      <div>
        <h1 className="text-titre-page leading-[1.45] tracking-[-0.01em]">{t.title}</h1>
        <p className="text-lg text-muted-foreground">
          {t.thisMonth}{" "}
          <strong className="font-extrabold numeric text-depenses-encre">
            {summary.data ? formatAmount(summary.data.total, currency) : "…"}
          </strong>
        </p>
      </div>

      <div className="flex flex-wrap items-start gap-5">
        <KitCard title={t.newExpense} className="flex min-w-0 flex-[3_1_460px] flex-col">
          <form
            noValidate
            className="flex flex-col gap-4"
            onSubmit={(event) => {
              event.preventDefault();
              submit();
            }}
          >
            {done && (
              <div
                role="status"
                className="flex items-center gap-3 rounded-champ bg-ventes-teinte px-4 py-3.5 font-bold text-marque"
              >
                <CheckCircle2 className="size-5 shrink-0" aria-hidden />
                {done}
              </div>
            )}
            {!categories.data ? (
              <Skeleton className="h-64 w-full" />
            ) : items.length === 0 ? (
              <p className="text-muted-foreground">{t.noCategories}</p>
            ) : (
              <div className="space-y-2">
                <p className="text-libelle">{t.forWhat}</p>
                <ChoiceTiles
                  label={t.forWhat}
                  value={categoryId}
                  onValueChange={(value) => {
                    setCategoryId(value);
                    setDone(null);
                  }}
                  rubrique="depenses"
                  className="grid-cols-[repeat(auto-fill,minmax(130px,1fr))]"
                  choices={items.map((item) => ({
                    value: item.id,
                    label: item.name,
                    icon: expenseIcon(item.name),
                  }))}
                />
              </div>
            )}
            <div className="space-y-2.5">
              <AmountField
                label={t.howMuch}
                value={amount}
                onChange={(value) => {
                  setAmount(value);
                  setDone(null);
                }}
                rubrique="depenses"
                placeholder={labels.payment.typeAmount}
              />
              <NumericPad
                value={amount}
                onChange={setAmount}
                rubrique="depenses"
                className="max-w-[420px]"
              />
            </div>
            <div className="flex flex-wrap gap-5">
              <div className="flex-[1_1_240px]">
                <WhenChips value={when} onChange={setWhen} timeZone={timeZone} />
              </div>
              {canPay && (
                <div className="flex-[1_1_240px]">
                  <PaymentMethodChips
                    value={method}
                    onChange={setMethod}
                    rubrique="depenses"
                    tone="teinte"
                    label={t.paidWith}
                  />
                </div>
              )}
            </div>
            <FieldError message={formError} />
            <button
              type="submit"
              disabled={!ready}
              className={cn(
                "flex min-h-[66px] items-center justify-center gap-2.5 rounded-bouton bg-depenses text-xl font-bold text-primary-foreground",
                "outline-none focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-45",
              )}
            >
              {create.isPending && <Loader2 className="size-6 animate-spin" aria-hidden />}
              {t.submit}
            </button>
          </form>
          <div className="mt-4 flex flex-wrap gap-x-5">
            <Can permission="expenses:create">
              <button
                type="button"
                onClick={() => setManaging(true)}
                className="min-h-11 font-semibold text-muted-foreground underline-offset-4 hover:underline pointer-coarse:min-h-12"
              >
                {t.manageTypes}
              </button>
            </Can>
            <Link
              href="/finance/expenses/all"
              className="inline-flex min-h-11 items-center font-semibold text-muted-foreground underline-offset-4 hover:underline pointer-coarse:min-h-12"
            >
              {t.allExpenses}
            </Link>
          </div>
        </KitCard>

        <KitCard title={t.byType} className="flex min-w-0 flex-[2_1_340px] flex-col">
          {summary.isError ? (
            <ErrorState error={summary.error} onRetry={() => void summary.refetch()} />
          ) : !summary.data ? (
            <Skeleton className="h-80 w-full" />
          ) : (
            <MonthSummary data={summary.data} currency={currency} today={today} />
          )}
        </KitCard>
      </div>

      <ExpenseCategoriesDialog open={managing} onOpenChange={setManaging} categories={items} />
    </div>
  );
}

function MonthSummary({
  data,
  currency,
  today,
}: {
  data: Schemas["ExpensesSummary"];
  currency: string;
  today: string;
}) {
  const largest = data.by_category.reduce(
    (max, row) => (wholeUnits(row.total) > max ? wholeUnits(row.total) : max),
    1n,
  );
  return (
    <>
      {data.by_category.length === 0 ? (
        <p className="text-muted-foreground">{t.noneYet}</p>
      ) : (
        <ul className="flex flex-col gap-3.5">
          {data.by_category.map((row) => (
            <li key={row.category_id}>
              <div className="flex items-baseline justify-between gap-3">
                <span className="font-bold">{row.name}</span>
                <span className="font-extrabold numeric">{formatAmount(row.total, currency)}</span>
              </div>
              <div aria-hidden className="mt-1.5 h-3 rounded-full bg-depenses-teinte">
                <div
                  className="h-3 rounded-full bg-depenses/80"
                  style={{
                    width: `${Math.max(2, Number((wholeUnits(row.total) * 100n) / largest))}%`,
                  }}
                />
              </div>
            </li>
          ))}
        </ul>
      )}
      <h2 className="mt-[22px] border-b border-filet pb-2 text-titre-carte">{t.latest}</h2>
      <ul>
        {data.recent.map((row) => (
          <li
            key={row.expense_id}
            className="flex items-center justify-between gap-3 border-b border-filet py-3"
          >
            <span className="min-w-0">
              <span className="block truncate font-bold">{row.category_name}</span>
              <span className="block text-muted-foreground">
                {t.latestLine(
                  dayText(row.spent_at, today),
                  row.method
                    ? (labels.paymentMethods[row.method as keyof typeof labels.paymentMethods] ??
                        row.method)
                    : t.notPaid,
                )}
              </span>
            </span>
            <span className="font-extrabold numeric text-depenses-encre">
              {MINUS}
              {formatAmount(row.amount, currency)}
            </span>
          </li>
        ))}
      </ul>
    </>
  );
}
