"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Pencil } from "lucide-react";
import Link from "next/link";
import { useState, type ReactNode } from "react";

import { ErrorState } from "@/components/error-state";
import { Money } from "@/components/money";
import { PageHeader } from "@/components/page-header";
import { SaleStatusBadge } from "@/components/status/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
import type { Schemas } from "@/lib/api/schema";
import { formatDate } from "@/lib/format";
import { labels } from "@/lib/labels";

import { CustomerFormDialog } from "../customer-form-dialog";

type DebtStatus = Schemas["DebtDetail"]["status"];

const DEBT_VARIANTS: Record<DebtStatus, "warning" | "success" | "neutral"> = {
  open: "warning",
  partially_paid: "warning",
  paid: "success",
  written_off: "neutral",
};

export function CustomerDetailView({ customerId }: { customerId: string }) {
  const { timeZone, currency } = useCompanyLocale();
  const [editing, setEditing] = useState(false);
  const customer = useQuery({
    queryKey: queryKeys.customers.detail(customerId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/customers/{customer_id}", {
          params: { path: { customer_id: customerId } },
        }),
      ),
  });

  if (customer.isError) {
    return <ErrorState error={customer.error} onRetry={() => void customer.refetch()} />;
  }
  if (!customer.data) return <Skeleton className="h-96 w-full" />;
  const data = customer.data;

  return (
    <>
      <Link
        href="/customers"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" aria-hidden />
        {labels.customers.backToList}
      </Link>
      <PageHeader
        title={data.name}
        count={data.code && <span className="numeric">{data.code}</span>}
        actions={
          <Can permission="customers:update">
            <Button variant="outline" onClick={() => setEditing(true)}>
              <Pencil aria-hidden />
              {labels.customers.edit}
            </Button>
          </Can>
        }
      />

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="space-y-6">
          <Purchases customerId={customerId} timeZone={timeZone} currency={currency} />
          <Can permission="debts:read">
            <Debts customerId={customerId} timeZone={timeZone} currency={currency} />
          </Can>
        </div>
        <Card>
          <CardHeader>
            <CardTitle>{labels.customers.contact}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <Row label={labels.customers.creditLimit}>
              {data.credit_limit ? (
                <Money value={data.credit_limit} currency={currency} className="font-semibold" />
              ) : (
                labels.customers.noLimit
              )}
            </Row>
            <Row label={labels.customers.phone}>
              <span className="numeric">{data.phone ?? "—"}</span>
            </Row>
            <Row label={labels.customers.email}>{data.email ?? "—"}</Row>
            <Row label={labels.customers.since}>
              <span className="numeric">{formatDate(data.created_at, timeZone)}</span>
            </Row>
          </CardContent>
        </Card>
      </div>

      <CustomerFormDialog customer={data} open={editing} onOpenChange={setEditing} />
    </>
  );
}

function Purchases({
  customerId,
  timeZone,
  currency,
}: {
  customerId: string;
  timeZone: string;
  currency: string;
}) {
  const params = { customer_id: customerId, page_size: 10 };
  const sales = useQuery({
    queryKey: queryKeys.sales.list(params),
    queryFn: () => unwrap(api.GET("/api/v1/sales", { params: { query: params } })),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>{labels.customers.purchases}</CardTitle>
        {sales.data && sales.data.total > 0 && (
          <CardAction>
            <span className="text-sm text-muted-foreground">
              {labels.sales.count(sales.data.total)}
            </span>
          </CardAction>
        )}
      </CardHeader>
      <CardContent>
        {sales.isError ? (
          <ErrorState error={sales.error} onRetry={() => void sales.refetch()} />
        ) : !sales.data ? (
          <Skeleton className="h-32 w-full" />
        ) : sales.data.items.length === 0 ? (
          <p className="text-sm text-muted-foreground">{labels.customers.noPurchases}</p>
        ) : (
          <ul className="-mx-2 divide-y">
            {sales.data.items.map((sale) => (
              <li key={sale.id}>
                <Link
                  href={sale.status === "draft" ? `/sales/${sale.id}/edit` : `/sales/${sale.id}`}
                  className="flex items-center justify-between gap-3 rounded-md px-2 py-2.5 hover:bg-muted/60"
                >
                  <div>
                    <p className="font-medium numeric">{sale.sale_no}</p>
                    <p className="text-sm numeric text-muted-foreground">
                      {formatDate(sale.sold_at, timeZone)}
                    </p>
                  </div>
                  <div className="flex items-center gap-3">
                    <SaleStatusBadge status={sale.status} hasReturns={sale.has_returns} />
                    <Money value={sale.total} currency={currency} className="font-medium" />
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function Debts({
  customerId,
  timeZone,
  currency,
}: {
  customerId: string;
  timeZone: string;
  currency: string;
}) {
  const params = { customer_id: customerId, page_size: 20 };
  const debts = useQuery({
    queryKey: queryKeys.debts.list(params),
    queryFn: () => unwrap(api.GET("/api/v1/debts", { params: { query: params } })),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>{labels.customers.debts}</CardTitle>
      </CardHeader>
      <CardContent>
        {debts.isError ? (
          <ErrorState error={debts.error} onRetry={() => void debts.refetch()} />
        ) : !debts.data ? (
          <Skeleton className="h-32 w-full" />
        ) : debts.data.items.length === 0 ? (
          <p className="text-sm text-muted-foreground">{labels.customers.noDebts}</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead className="px-4">{labels.customers.debtColumns.created}</TableHead>
                  <TableHead className="px-4 text-right">
                    {labels.customers.debtColumns.principal}
                  </TableHead>
                  <TableHead className="px-4 text-right">
                    {labels.customers.debtColumns.paid}
                  </TableHead>
                  <TableHead className="px-4 text-right">
                    {labels.customers.debtColumns.balance}
                  </TableHead>
                  <TableHead className="px-4">{labels.customers.debtColumns.due}</TableHead>
                  <TableHead className="px-4">{labels.customers.debtColumns.status}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {debts.data.items.map((debt) => (
                  <TableRow key={debt.id}>
                    <TableCell className="px-4 numeric">
                      {debt.sale_id ? (
                        <Link href={`/sales/${debt.sale_id}`} className="hover:underline">
                          {formatDate(debt.created_at, timeZone)}
                        </Link>
                      ) : (
                        formatDate(debt.created_at, timeZone)
                      )}
                    </TableCell>
                    <TableCell className="px-4 text-right">
                      <Money value={debt.principal} currency={currency} />
                    </TableCell>
                    <TableCell className="px-4 text-right">
                      <Money value={debt.amount_paid} currency={currency} />
                    </TableCell>
                    <TableCell className="px-4 text-right">
                      <Money value={debt.balance} currency={currency} className="font-medium" />
                    </TableCell>
                    <TableCell className="px-4 numeric">
                      {formatDate(debt.due_date, timeZone)}
                    </TableCell>
                    <TableCell className="px-4">
                      <Badge variant={DEBT_VARIANTS[debt.status]}>
                        {labels.debtStatus[debt.status]}
                      </Badge>
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
