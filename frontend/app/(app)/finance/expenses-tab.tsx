"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Plus, Tags } from "lucide-react";
import { useState } from "react";

import { ErrorState } from "@/components/error-state";
import { FilterChips, MoreButton, OUTLINE_ACTION } from "@/components/kit/filter-chips";
import { ListRow } from "@/components/kit/list-row";
import { Skeleton } from "@/components/ui/skeleton";
import { useCompanyLocale } from "@/hooks/use-me";
import { usePeriod } from "@/hooks/use-period";
import { Can, usePermission } from "@/hooks/use-permission";
import { useTableParams } from "@/hooks/use-table-params";
import { api, unwrap } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { compareDecimal, subtractDecimal } from "@/lib/decimal";
import { expenseIcon } from "@/lib/expense-icons";
import { formatAmount, formatDate } from "@/lib/format";
import { labels } from "@/lib/labels";
import { MINUS } from "@/lib/money";
import { cn } from "@/lib/utils";

import { ExpenseCategoriesDialog } from "./expense-categories-dialog";
import { ExpenseDialog } from "./expense-dialog";
import { PaymentDialog, type ExpenseTarget } from "./payment-dialog";

type Expense = Schemas["ExpenseRead"];
type PaidState = keyof typeof labels.finance.expenses.status;
const t = labels.finance.expenses;

const PAID_TONES: Record<PaidState, string> = {
  paid: "bg-ventes-teinte text-ventes-encre",
  partial: "bg-stock-teinte text-stock-encre",
  unpaid: "bg-voile text-encre-2",
};

/** État d'affichage : comparaison du réglé servi par l'API au montant, sans calcul. */
function paidState(expense: Expense): PaidState {
  if (compareDecimal(expense.amount_paid, expense.amount) !== -1) return "paid";
  return compareDecimal(expense.amount_paid, "0") === 1 ? "partial" : "unpaid";
}

/**
 * « Toutes les dépenses » (ADR 0073), dans le style de la maquette v2 : une puce par type de
 * dépense, une ligne par dépense avec l'icône de son type, son montant en orange et son
 * état ; « Régler » sur celles qui ne le sont pas.
 */
export function ExpensesTab() {
  const table = useTableParams();
  const period = usePeriod();
  const { timeZone, currency } = useCompanyLocale();
  const canPay = usePermission("payments:create");
  const [creating, setCreating] = useState(false);
  const [editingCategories, setEditingCategories] = useState(false);
  const [paying, setPaying] = useState<ExpenseTarget | null>(null);

  const categoryId = table.get("category");
  const filters = {
    page_size: table.pageSize,
    from: period.from,
    to: period.to,
    category_id: categoryId ?? undefined,
  };
  const query = useInfiniteQuery({
    queryKey: queryKeys.expenses.list({ ...filters, infinite: true }),
    initialPageParam: 1,
    queryFn: ({ pageParam }) =>
      unwrap(api.GET("/api/v1/expenses", { params: { query: { ...filters, page: pageParam } } })),
    getNextPageParam: (last) =>
      last.page * last.page_size < last.total ? last.page + 1 : undefined,
  });
  const categories = useQuery({
    queryKey: queryKeys.expenseCategories.all,
    queryFn: () =>
      unwrap(api.GET("/api/v1/expense-categories", { params: { query: { page_size: 100 } } })),
  });
  const categoryItems = categories.data?.items ?? [];
  const expenses = query.data?.pages.flatMap((page) => page.items) ?? [];
  const total = query.data?.pages[0]?.total;

  return (
    <>
      <div className="flex flex-col gap-3">
        <FilterChips
          label={t.categoryFilter}
          value={categoryId}
          allLabel={t.allCategories}
          options={categoryItems.map((category) => [category.id, category.name] as const)}
          onChange={(next) => table.setFilter("category", next)}
        />
        <div className="flex flex-wrap items-center gap-2">
          <span className="mr-auto text-muted-foreground">
            {total !== undefined ? t.count(total) : null}
          </span>
          <button
            type="button"
            className={OUTLINE_ACTION}
            onClick={() => setEditingCategories(true)}
          >
            <Tags className="size-5" aria-hidden />
            {t.categories}
          </button>
          <Can permission="expenses:create">
            <button
              type="button"
              onClick={() => setCreating(true)}
              className="inline-flex min-h-cible items-center gap-2 rounded-champ bg-depenses px-4 font-bold text-primary-foreground outline-none hover:brightness-95 focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              <Plus className="size-5" aria-hidden />
              {t.add}
            </button>
          </Can>
        </div>
      </div>

      <section className="rounded-carte border border-border bg-card px-carte pb-2">
        {query.isError ? (
          <div className="py-carte">
            <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          </div>
        ) : !query.data ? (
          <Skeleton className="my-carte h-64 w-full rounded-champ" />
        ) : expenses.length === 0 ? (
          <p className="py-carte text-muted-foreground">{t.empty}</p>
        ) : (
          <ul
            aria-label={labels.moneyScreens.expensesScreen.allExpenses}
            className="[&>li:first-child>*]:border-t-0"
          >
            {expenses.map((expense) => {
              const state = paidState(expense);
              const Icon = expenseIcon(expense.category_name);
              return (
                <li key={expense.id}>
                  <ListRow
                    wrap
                    className="flex-wrap"
                    leading={
                      <span
                        aria-hidden
                        className="flex size-11 shrink-0 items-center justify-center rounded-mini bg-depenses-teinte text-depenses-encre"
                      >
                        <Icon className="size-[22px]" />
                      </span>
                    }
                    title={expense.label || expense.category_name}
                    subtitle={
                      <>
                        {expense.category_name} · {t.kind[expense.kind]} ·{" "}
                        <span className="numeric">{formatDate(expense.spent_at, timeZone)}</span> ·{" "}
                        <span className="numeric">{expense.expense_no}</span>
                      </>
                    }
                    trailing={
                      <>
                        <span className="font-extrabold numeric text-depenses-encre">
                          {MINUS}
                          {formatAmount(expense.amount, currency)}
                        </span>
                        <span
                          className={cn(
                            "inline-flex items-center rounded-full px-3 py-1.5 text-sm font-bold",
                            PAID_TONES[state],
                          )}
                        >
                          {t.status[state]}
                        </span>
                        {canPay && state !== "paid" && (
                          <button
                            type="button"
                            className={OUTLINE_ACTION}
                            onClick={() =>
                              setPaying({
                                id: expense.id,
                                label: expense.label,
                                // Reste à régler proposé ; le serveur contrôle le décaissement.
                                suggested:
                                  subtractDecimal(expense.amount, expense.amount_paid) ??
                                  expense.amount,
                              })
                            }
                          >
                            {t.pay}
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

      <ExpenseDialog open={creating} onOpenChange={setCreating} categories={categoryItems} />
      <ExpenseCategoriesDialog
        open={editingCategories}
        onOpenChange={setEditingCategories}
        categories={categoryItems}
      />
      {paying && (
        <PaymentDialog
          key={paying.id}
          open
          onOpenChange={(open) => !open && setPaying(null)}
          expense={paying}
        />
      )}
    </>
  );
}
