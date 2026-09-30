"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Plus, Tags } from "lucide-react";
import { useState } from "react";

import { DataTable, type Column } from "@/components/data-table";
import { ErrorState } from "@/components/error-state";
import { Money } from "@/components/money";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useCompanyLocale } from "@/hooks/use-me";
import { usePeriod } from "@/hooks/use-period";
import { Can, usePermission } from "@/hooks/use-permission";
import { useTableParams } from "@/hooks/use-table-params";
import { api, unwrap } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { compareDecimal, subtractDecimal } from "@/lib/decimal";
import { formatDate } from "@/lib/format";
import { labels } from "@/lib/labels";

import { ExpenseCategoriesDialog } from "./expense-categories-dialog";
import { ExpenseDialog } from "./expense-dialog";
import { PaymentDialog, type ExpenseTarget } from "./payment-dialog";

type Expense = Schemas["ExpenseRead"];
type PaidState = keyof typeof labels.finance.expenses.status;

const ALL = "all";
const PAID_VARIANTS: Record<PaidState, "success" | "warning" | "neutral"> = {
  paid: "success",
  partial: "warning",
  unpaid: "neutral",
};

/** État d'affichage : comparaison du réglé servi par l'API au montant, sans calcul. */
function paidState(expense: Expense): PaidState {
  if (compareDecimal(expense.amount_paid, expense.amount) !== -1) return "paid";
  return compareDecimal(expense.amount_paid, "0") === 1 ? "partial" : "unpaid";
}

/** Charges de la période (`GET /expenses`), leur règlement et leurs catégories. */
export function ExpensesTab() {
  const table = useTableParams();
  const period = usePeriod();
  const { timeZone, currency } = useCompanyLocale();
  const canPay = usePermission("payments:create");
  const [creating, setCreating] = useState(false);
  const [editingCategories, setEditingCategories] = useState(false);
  const [paying, setPaying] = useState<ExpenseTarget | null>(null);
  const t = labels.finance.expenses;

  const categoryId = table.get("category");
  const params = {
    page: table.page,
    page_size: table.pageSize,
    from: period.from,
    to: period.to,
    category_id: categoryId ?? undefined,
  };
  const query = useQuery({
    queryKey: queryKeys.expenses.list(params),
    queryFn: () => unwrap(api.GET("/api/v1/expenses", { params: { query: params } })),
    placeholderData: keepPreviousData,
  });
  const categories = useQuery({
    queryKey: queryKeys.expenseCategories.all,
    queryFn: () =>
      unwrap(api.GET("/api/v1/expense-categories", { params: { query: { page_size: 100 } } })),
  });
  const categoryItems = categories.data?.items ?? [];

  const columns: Column<Expense>[] = [
    {
      id: "number",
      header: t.columns.number,
      cell: (expense) => <span className="font-medium numeric">{expense.expense_no}</span>,
    },
    {
      id: "date",
      header: t.columns.date,
      cell: (expense) => <span className="numeric">{formatDate(expense.spent_at, timeZone)}</span>,
    },
    { id: "label", header: t.columns.label, cell: (expense) => expense.label },
    {
      id: "category",
      header: t.columns.category,
      cell: (expense) => (
        <span className="flex items-center gap-2">
          {expense.category_name}
          <span className="text-xs text-muted-foreground">{t.kind[expense.kind]}</span>
        </span>
      ),
    },
    {
      id: "amount",
      header: t.columns.amount,
      numeric: true,
      cell: (expense) => (
        <Money value={expense.amount} currency={currency} className="font-medium" />
      ),
    },
    {
      id: "paid",
      header: t.columns.paid,
      numeric: true,
      cell: (expense) => <Money value={expense.amount_paid} currency={currency} />,
    },
    {
      id: "status",
      header: t.columns.status,
      cell: (expense) => {
        const state = paidState(expense);
        return (
          <span className="flex items-center justify-between gap-2">
            <Badge variant={PAID_VARIANTS[state]}>{t.status[state]}</Badge>
            {canPay && state !== "paid" && (
              <Button
                variant="outline"
                size="sm"
                onClick={() =>
                  setPaying({
                    id: expense.id,
                    label: expense.label,
                    // Préremplissage du reste à régler ; le serveur contrôle le décaissement.
                    suggested:
                      subtractDecimal(expense.amount, expense.amount_paid) ?? expense.amount,
                  })
                }
              >
                {t.pay}
              </Button>
            )}
          </span>
        );
      },
    },
  ];

  return (
    <>
      {query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <DataTable
          caption={labels.finance.tabs.expenses}
          columns={columns}
          rows={query.data?.items}
          rowKey={(expense) => expense.id}
          total={query.data?.total ?? 0}
          page={table.page}
          pageSize={table.pageSize}
          onPageChange={table.setPage}
          loading={query.isFetching}
          empty={t.empty}
          filters={
            <div className="flex w-full flex-wrap items-center gap-2">
              <Select
                value={categoryId ?? ALL}
                onValueChange={(value) => table.setFilter("category", value === ALL ? null : value)}
              >
                <SelectTrigger aria-label={t.categoryFilter} className="w-56">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>{t.allCategories}</SelectItem>
                  {categoryItems.map((category) => (
                    <SelectItem key={category.id} value={category.id}>
                      {category.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <span className="ml-auto text-sm text-muted-foreground">
                {query.data ? t.count(query.data.total) : null}
              </span>
              <Button variant="outline" onClick={() => setEditingCategories(true)}>
                <Tags aria-hidden />
                {t.categories}
              </Button>
              <Can permission="expenses:create">
                <Button onClick={() => setCreating(true)}>
                  <Plus aria-hidden />
                  {t.add}
                </Button>
              </Can>
            </div>
          }
        />
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
