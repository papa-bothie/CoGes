"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { ErrorState } from "@/components/error-state";
import { Money } from "@/components/money";
import { Badge } from "@/components/ui/badge";
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
import { api, unwrap } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { formatDate } from "@/lib/format";
import { labels } from "@/lib/labels";

type DebtStatus = Schemas["DebtDetail"]["status"];

const DEBT_VARIANTS: Record<DebtStatus, "warning" | "success" | "neutral"> = {
  open: "warning",
  partially_paid: "warning",
  paid: "success",
  written_off: "neutral",
};

/**
 * Dettes d'un tiers (`/debts?customer_id=` ou `?supplier_id=`, ADR 0050), telles que l'API
 * les renvoie : montant, déjà payé, solde, échéance, statut. Aucun cumul calculé ici.
 */
export function DebtsCard({
  title,
  empty,
  filter,
}: {
  title: string;
  empty: string;
  filter: { customer_id: string } | { supplier_id: string };
}) {
  const { timeZone, currency } = useCompanyLocale();
  const params = { ...filter, page_size: 20 };
  const debts = useQuery({
    queryKey: queryKeys.debts.list(params),
    queryFn: () => unwrap(api.GET("/api/v1/debts", { params: { query: params } })),
  });
  const columns = labels.customers.debtColumns;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent>
        {debts.isError ? (
          <ErrorState error={debts.error} onRetry={() => void debts.refetch()} />
        ) : !debts.data ? (
          <Skeleton className="h-32 w-full" />
        ) : debts.data.items.length === 0 ? (
          <p className="text-sm text-muted-foreground">{empty}</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead className="px-4">{columns.created}</TableHead>
                  <TableHead className="px-4 text-right">{columns.principal}</TableHead>
                  <TableHead className="px-4 text-right">{columns.paid}</TableHead>
                  <TableHead className="px-4 text-right">{columns.balance}</TableHead>
                  <TableHead className="px-4">{columns.due}</TableHead>
                  <TableHead className="px-4">{columns.status}</TableHead>
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
