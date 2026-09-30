"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Pencil } from "lucide-react";
import Link from "next/link";
import { useState, type ReactNode } from "react";

import { ErrorState } from "@/components/error-state";
import { DebtsCard } from "@/components/finance/debts-card";
import { Money } from "@/components/money";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useCompanyLocale } from "@/hooks/use-me";
import { Can } from "@/hooks/use-permission";
import { api, unwrap } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries/keys";
import { formatDate } from "@/lib/format";
import { labels } from "@/lib/labels";

import { SupplierFormDialog } from "../supplier-form-dialog";

export function SupplierDetailView({ supplierId }: { supplierId: string }) {
  const { timeZone } = useCompanyLocale();
  const [editing, setEditing] = useState(false);
  const supplier = useQuery({
    queryKey: queryKeys.suppliers.detail(supplierId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/suppliers/{supplier_id}", {
          params: { path: { supplier_id: supplierId } },
        }),
      ),
  });

  if (supplier.isError) {
    return <ErrorState error={supplier.error} onRetry={() => void supplier.refetch()} />;
  }
  if (!supplier.data) return <Skeleton className="h-96 w-full" />;
  const data = supplier.data;

  return (
    <>
      <Link
        href="/suppliers"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" aria-hidden />
        {labels.suppliers.backToList}
      </Link>
      <PageHeader
        title={data.name}
        count={data.code && <span className="numeric">{data.code}</span>}
        actions={
          <Can permission="suppliers:update">
            <Button variant="outline" onClick={() => setEditing(true)}>
              <Pencil aria-hidden />
              {labels.suppliers.edit}
            </Button>
          </Can>
        }
      />

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="space-y-6">
          <Can permission="expenses:read">
            <Expenses supplierId={supplierId} />
          </Can>
          <Can permission="debts:read">
            <DebtsCard
              title={labels.suppliers.debts}
              empty={labels.suppliers.noDebts}
              filter={{ supplier_id: supplierId }}
            />
          </Can>
        </div>
        <Card>
          <CardHeader>
            <CardTitle>{labels.suppliers.contact}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <Row label={labels.suppliers.terms}>
              <span className="font-semibold">
                {data.payment_terms_days === null
                  ? labels.suppliers.noTerms
                  : labels.suppliers.termsDays(data.payment_terms_days)}
              </span>
            </Row>
            <Row label={labels.suppliers.phone}>
              <span className="numeric">{data.phone ?? "—"}</span>
            </Row>
            <Row label={labels.suppliers.since}>
              <span className="numeric">{formatDate(data.created_at, timeZone)}</span>
            </Row>
          </CardContent>
        </Card>
      </div>

      <SupplierFormDialog supplier={data} open={editing} onOpenChange={setEditing} />
    </>
  );
}

/** Charges rattachées au fournisseur (`/expenses?supplier_id=`), les plus récentes d'abord. */
function Expenses({ supplierId }: { supplierId: string }) {
  const { timeZone, currency } = useCompanyLocale();
  const params = { supplier_id: supplierId, page_size: 10 };
  const expenses = useQuery({
    queryKey: ["expenses", "list", params],
    queryFn: () => unwrap(api.GET("/api/v1/expenses", { params: { query: params } })),
  });
  const columns = labels.suppliers.expenseColumns;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{labels.suppliers.expenses}</CardTitle>
      </CardHeader>
      <CardContent>
        {expenses.isError ? (
          <ErrorState error={expenses.error} onRetry={() => void expenses.refetch()} />
        ) : !expenses.data ? (
          <Skeleton className="h-32 w-full" />
        ) : expenses.data.items.length === 0 ? (
          <p className="text-sm text-muted-foreground">{labels.suppliers.noExpenses}</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead className="px-4">{columns.number}</TableHead>
                  <TableHead className="px-4">{columns.date}</TableHead>
                  <TableHead className="px-4">{columns.label}</TableHead>
                  <TableHead className="px-4">{columns.category}</TableHead>
                  <TableHead className="px-4 text-right">{columns.amount}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {expenses.data.items.map((expense) => (
                  <TableRow key={expense.id}>
                    <TableCell className="px-4 numeric">{expense.expense_no}</TableCell>
                    <TableCell className="px-4 numeric">
                      {formatDate(expense.spent_at, timeZone)}
                    </TableCell>
                    <TableCell className="px-4">{expense.label}</TableCell>
                    <TableCell className="px-4 text-muted-foreground">
                      {expense.category_name}
                    </TableCell>
                    <TableCell className="px-4 text-right">
                      <Money value={expense.amount} currency={currency} className="font-medium" />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
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
