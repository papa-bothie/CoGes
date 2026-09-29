"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Loader2 } from "lucide-react";
import Link from "next/link";
import { useState, type ReactNode } from "react";
import { toast } from "sonner";

import { ErrorState } from "@/components/error-state";
import { FieldError } from "@/components/field-error";
import { Money } from "@/components/money";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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
import { errorMessage } from "@/lib/api/errors";
import { useIdempotencyKey } from "@/lib/api/idempotency";
import { queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { compareDecimal, parseDecimalInput, toInputDecimal } from "@/lib/decimal";
import { formatDate, formatDateTime, formatQty } from "@/lib/format";
import { labels } from "@/lib/labels";

type SaleReturn = Schemas["SaleReturnDetail"];
type SaleDetail = Schemas["SaleDetail"];
type RefundMethod = Schemas["RefundCreate"]["method"];

const CASH_METHODS: readonly RefundMethod[] = [
  "cash",
  "mobile_money",
  "bank_transfer",
  "card",
  "cheque",
];

const STATUS_VARIANTS = {
  none_due: "neutral",
  pending: "warning",
  partial: "warning",
  settled: "success",
} as const;

/**
 * Second temps d'un retour : le montant remboursable **calculé par le serveur**, puis le
 * règlement — en trésorerie, par compensation de la dette ouverte (ADR 0024), ou plus
 * tard, en une ou plusieurs fois (ADR 0025).
 */
export function ReturnDetailView({ returnId }: { returnId: string }) {
  const { timeZone, currency } = useCompanyLocale();

  const saleReturn = useQuery({
    queryKey: queryKeys.saleReturns.detail(returnId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/sale-returns/{return_id}", {
          params: { path: { return_id: returnId } },
        }),
      ),
  });
  const saleId = saleReturn.data?.sale_id;
  const sale = useQuery({
    queryKey: queryKeys.sales.detail(saleId ?? ""),
    queryFn: () =>
      unwrap(api.GET("/api/v1/sales/{sale_id}", { params: { path: { sale_id: saleId! } } })),
    enabled: Boolean(saleId),
  });

  if (saleReturn.isError) {
    return <ErrorState error={saleReturn.error} onRetry={() => void saleReturn.refetch()} />;
  }
  if (!saleReturn.data) return <Skeleton className="h-96 w-full" />;

  const data = saleReturn.data;
  const saleItems = new Map(sale.data?.items.map((item) => [item.id, item]));
  const due = compareDecimal(data.refund_due, "0") === 1;

  return (
    <>
      <Link
        href={`/sales/${data.sale_id}`}
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" aria-hidden />
        {labels.receipt.back}
      </Link>
      <PageHeader
        title={labels.returns.title(data.return_no)}
        count={
          <span className="flex items-center gap-2">
            {sale.data && labels.returns.ofSale(sale.data.sale_no)}
            <Badge variant={STATUS_VARIANTS[data.refund_status]}>
              {labels.returns.refundStatus[data.refund_status]}
            </Badge>
          </span>
        }
      />

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>{labels.returns.items}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="overflow-x-auto rounded-lg border">
                <Table>
                  <TableHeader>
                    <TableRow className="hover:bg-transparent">
                      <TableHead className="px-4">{labels.sales.lineColumns.product}</TableHead>
                      <TableHead className="px-4 text-right">
                        {labels.sales.lineColumns.qty}
                      </TableHead>
                      <TableHead className="px-4 text-right">{labels.returns.taxRefund}</TableHead>
                      <TableHead className="px-4 text-right">
                        {labels.returns.refundAmount}
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.items.map((item) => {
                      const line = saleItems.get(item.sale_item_id);
                      return (
                        <TableRow key={item.id}>
                          <TableCell className="px-4">
                            {line ? (
                              <>
                                <p className="font-medium">
                                  {line.product_name ?? labels.sales.deletedProduct}
                                </p>
                                <p className="text-xs numeric text-muted-foreground">{line.sku}</p>
                              </>
                            ) : (
                              <Skeleton className="h-4 w-32" />
                            )}
                          </TableCell>
                          <TableCell className="px-4 text-right numeric">
                            {formatQty(item.qty)}
                          </TableCell>
                          <TableCell className="px-4 text-right">
                            <Money value={item.tax_refund} currency={currency} />
                          </TableCell>
                          <TableCell className="px-4 text-right">
                            <Money
                              value={item.refund_amount}
                              currency={currency}
                              className="font-medium"
                            />
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </div>
              {data.reason && <p className="mt-3 text-sm text-muted-foreground">{data.reason}</p>}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>{labels.returns.refunds}</CardTitle>
            </CardHeader>
            <CardContent>
              {data.payments.length === 0 ? (
                <p className="text-sm text-muted-foreground">{labels.returns.noRefunds}</p>
              ) : (
                <ul className="divide-y">
                  {data.payments.map((payment) => (
                    <li key={payment.id} className="flex items-center justify-between gap-3 py-2.5">
                      <div>
                        <p className="font-medium">
                          {labels.paymentMethods[payment.method]}
                          {payment.cancelled && (
                            <Badge variant="danger" className="ml-2">
                              {labels.sales.paymentCancelled}
                            </Badge>
                          )}
                        </p>
                        <p className="text-sm numeric text-muted-foreground">
                          {formatDateTime(payment.paid_at, timeZone)}
                          {payment.reference && ` · ${payment.reference}`}
                        </p>
                      </div>
                      <Money value={payment.amount} currency={currency} className="font-medium" />
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </div>

        <div className="space-y-6">
          <Card>
            <CardContent className="space-y-2 text-sm">
              <Row label={labels.returns.returnedAt}>
                <span className="numeric">{formatDate(data.returned_at, timeZone)}</span>
              </Row>
              <Row label={labels.returns.totalRefund}>
                <Money value={data.total_refund} currency={currency} className="font-medium" />
              </Row>
              <Row label={labels.returns.refunded}>
                <Money value={data.refunded_total} currency={currency} />
              </Row>
              <div className="flex items-baseline justify-between border-t pt-3">
                <span className="font-semibold">{labels.returns.refundDue}</span>
                <Money value={data.refund_due} currency={currency} className="text-xl font-bold" />
              </div>
            </CardContent>
          </Card>

          {due && (
            <Can
              permission="sale_returns:confirm"
              fallback={
                <p className="text-sm text-muted-foreground">{labels.returns.managerOnly}</p>
              }
            >
              <RefundForm saleReturn={data} sale={sale.data} />
            </Can>
          )}
        </div>
      </div>
    </>
  );
}

function RefundForm({
  saleReturn,
  sale,
}: {
  saleReturn: SaleReturn;
  sale: SaleDetail | undefined;
}) {
  const queryClient = useQueryClient();
  const idempotency = useIdempotencyKey();
  const [amount, setAmount] = useState(toInputDecimal(saleReturn.refund_due));
  const [method, setMethod] = useState<RefundMethod>("cash");
  const [reference, setReference] = useState("");
  const [error, setError] = useState<string | null>(null);

  // La compensation n'a de sens que si la vente porte une dette encore ouverte (ADR 0024).
  const canOffset =
    sale?.debt != null &&
    (sale.debt.status === "open" || sale.debt.status === "partially_paid") &&
    compareDecimal(sale.debt.balance, "0") === 1;
  const methods = canOffset ? [...CASH_METHODS, "offset" as const] : CASH_METHODS;

  const refund = useMutation({
    meta: { toastError: false },
    mutationFn: (value: string) =>
      unwrap(
        api.POST("/api/v1/sale-returns/{return_id}/refunds", {
          params: { path: { return_id: saleReturn.id } },
          body: { amount: value, method, reference: reference.trim() || null },
          headers: idempotency.headers,
        }),
      ),
    onSuccess: (updated) => {
      idempotency.renew();
      queryClient.setQueryData(queryKeys.saleReturns.detail(updated.id), updated);
      setAmount(toInputDecimal(updated.refund_due));
      setReference("");
      for (const key of [queryKeys.sales.all, queryKeys.dashboard, queryKeys.debts.all]) {
        void queryClient.invalidateQueries({ queryKey: key });
      }
      toast.success(labels.returns.refundDone);
    },
    onError: (failure) => setError(errorMessage(failure)),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>{labels.returns.settle}</CardTitle>
        <CardDescription>{labels.returns.settleIntro}</CardDescription>
      </CardHeader>
      <CardContent>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            const value = parseDecimalInput(amount);
            if (value === null || compareDecimal(value, "0") !== 1) {
              setError(labels.sales.invalidNumber);
              return;
            }
            setError(null);
            refund.mutate(value);
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor="refund-amount">{labels.returns.amount}</Label>
            <Input
              id="refund-amount"
              inputMode="decimal"
              value={amount}
              aria-invalid={Boolean(error)}
              aria-describedby={error ? "refund-error" : undefined}
              onChange={(event) => setAmount(event.target.value)}
              className="h-9 text-right numeric"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="refund-method">{labels.returns.method}</Label>
            <Select value={method} onValueChange={(value) => setMethod(value as RefundMethod)}>
              <SelectTrigger id="refund-method" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {methods.map((value) => (
                  <SelectItem key={value} value={value}>
                    {labels.paymentMethods[value]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {method !== "offset" && (
            <div className="space-y-1.5">
              <Label htmlFor="refund-reference">{labels.returns.reference}</Label>
              <Input
                id="refund-reference"
                value={reference}
                onChange={(event) => setReference(event.target.value)}
                className="h-9"
              />
            </div>
          )}
          <FieldError id="refund-error" message={error} />
          <div className="flex flex-col gap-2">
            <Button type="submit" disabled={refund.isPending}>
              {refund.isPending && <Loader2 className="animate-spin" aria-hidden />}
              {labels.returns.refundSubmit}
            </Button>
            <Button variant="outline" asChild>
              <Link href={`/sales/${saleReturn.sale_id}`}>{labels.returns.later}</Link>
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="text-muted-foreground">{label}</span>
      {children}
    </div>
  );
}
