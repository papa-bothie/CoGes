"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Ban, Pencil, Printer, Undo2 } from "lucide-react";
import Link from "next/link";
import { useState, type ReactNode } from "react";
import { toast } from "sonner";

import { ErrorState } from "@/components/error-state";
import { FieldError } from "@/components/field-error";
import { Money } from "@/components/money";
import { PageHeader } from "@/components/page-header";
import { SaleStatusBadge } from "@/components/status/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { useCompanyLocale, useMe } from "@/hooks/use-me";
import { Can } from "@/hooks/use-permission";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { compareDecimal } from "@/lib/decimal";
import { formatDate, formatDateTime, formatQty } from "@/lib/format";
import { labels } from "@/lib/labels";

type SaleDetail = Schemas["SaleDetail"];

export function SaleDetailView({ saleId }: { saleId: string }) {
  const { timeZone, currency } = useCompanyLocale();
  const { data: me } = useMe();
  const showTax = me?.company.tax_enabled ?? true;
  const [cancelOpen, setCancelOpen] = useState(false);

  const sale = useQuery({
    queryKey: queryKeys.sales.detail(saleId),
    queryFn: () =>
      unwrap(api.GET("/api/v1/sales/{sale_id}", { params: { path: { sale_id: saleId } } })),
  });
  const returns = useQuery({
    queryKey: queryKeys.sales.returns(saleId),
    queryFn: () =>
      unwrap(api.GET("/api/v1/sales/{sale_id}/returns", { params: { path: { sale_id: saleId } } })),
    enabled: sale.data?.status === "confirmed",
  });

  if (sale.isError) return <ErrorState error={sale.error} onRetry={() => void sale.refetch()} />;
  if (!sale.data) return <DetailSkeleton />;

  const data = sale.data;
  const returnable = data.items.some((item) => compareDecimal(item.qty, item.returned_qty) === 1);

  return (
    <>
      <Link
        href="/sales"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" aria-hidden />
        {labels.sales.backToList}
      </Link>
      <PageHeader
        title={labels.sales.editTitle(data.sale_no)}
        count={<SaleStatusBadge status={data.status} hasReturns={data.has_returns} />}
        actions={
          <>
            {data.status === "draft" && (
              <Can permission="sales:update">
                <Button asChild>
                  <Link href={`/sales/${data.id}/edit`}>
                    <Pencil aria-hidden />
                    {labels.sales.resume}
                  </Link>
                </Button>
              </Can>
            )}
            {data.status !== "draft" && (
              <Button variant="outline" asChild>
                <Link href={`/sales/${data.id}/receipt`}>
                  <Printer aria-hidden />
                  {labels.sales.receipt}
                </Link>
              </Button>
            )}
            {data.status === "confirmed" && returnable && (
              <Can permission="sale_returns:create">
                <Button variant="outline" asChild>
                  <Link href={`/sales/${data.id}/returns/new`}>
                    <Undo2 aria-hidden />
                    {labels.sales.makeReturn}
                  </Link>
                </Button>
              </Can>
            )}
            {data.status === "confirmed" && (
              <Can permission="sales:cancel">
                <Button variant="destructive" onClick={() => setCancelOpen(true)}>
                  <Ban aria-hidden />
                  {labels.sales.cancel}
                </Button>
              </Can>
            )}
          </>
        }
      />

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>{labels.sales.lines}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="overflow-x-auto rounded-lg border">
                <Table>
                  <TableHeader>
                    <TableRow className="hover:bg-transparent">
                      <TableHead className="px-4">{labels.sales.lineColumns.product}</TableHead>
                      <TableHead className="px-4 text-right">
                        {labels.sales.lineColumns.unitPrice}
                      </TableHead>
                      <TableHead className="px-4 text-right">
                        {labels.sales.lineColumns.qty}
                      </TableHead>
                      {data.has_returns && (
                        <TableHead className="px-4 text-right">
                          {labels.sales.returnedQty}
                        </TableHead>
                      )}
                      <TableHead className="px-4 text-right">
                        {labels.sales.lineColumns.discount}
                      </TableHead>
                      {showTax && (
                        <TableHead className="px-4 text-right">
                          {labels.sales.lineColumns.tax}
                        </TableHead>
                      )}
                      <TableHead className="px-4 text-right">
                        {labels.sales.lineColumns.total}
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.items.map((item) => (
                      <TableRow key={item.id}>
                        <TableCell className="px-4">
                          <p className="font-medium">
                            {item.product_name ?? labels.sales.deletedProduct}
                          </p>
                          <p className="text-xs numeric text-muted-foreground">{item.sku}</p>
                        </TableCell>
                        <TableCell className="px-4 text-right">
                          <Money value={item.unit_price} currency={currency} />
                        </TableCell>
                        <TableCell className="px-4 text-right numeric">
                          {formatQty(item.qty)}
                        </TableCell>
                        {data.has_returns && (
                          <TableCell className="px-4 text-right numeric">
                            {formatQty(item.returned_qty)}
                          </TableCell>
                        )}
                        <TableCell className="px-4 text-right">
                          <Money value={item.discount} currency={currency} />
                        </TableCell>
                        {showTax && (
                          <TableCell className="px-4 text-right">
                            <Money value={item.tax_amount} currency={currency} />
                          </TableCell>
                        )}
                        <TableCell className="px-4 text-right">
                          <Money
                            value={item.line_total}
                            currency={currency}
                            className="font-medium"
                          />
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>{labels.sales.payments}</CardTitle>
            </CardHeader>
            <CardContent>
              {data.payments.length === 0 ? (
                <p className="text-sm text-muted-foreground">{labels.sales.noPayments}</p>
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
                      <Money
                        value={payment.amount}
                        currency={currency}
                        className={
                          payment.cancelled ? "text-muted-foreground line-through" : "font-medium"
                        }
                      />
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          {data.status === "confirmed" && (returns.data?.items.length ?? 0) > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>{labels.sales.returns}</CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="-mx-2 divide-y">
                  {returns.data?.items.map((item) => (
                    <li key={item.id}>
                      <Link
                        href={`/sales/returns/${item.id}`}
                        className="flex items-center justify-between gap-3 rounded-md px-2 py-2.5 hover:bg-muted/60"
                      >
                        <div>
                          <p className="font-medium numeric">{item.return_no}</p>
                          <p className="text-sm numeric text-muted-foreground">
                            {formatDate(item.returned_at, timeZone)}
                          </p>
                        </div>
                        <div className="text-right">
                          <Money
                            value={item.total_refund}
                            currency={currency}
                            className="font-medium"
                          />
                          <p className="text-sm text-muted-foreground">
                            {labels.returns.refundStatus[item.refund_status]}
                          </p>
                        </div>
                      </Link>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}
        </div>

        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>{labels.sales.totals}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <Row label={labels.sales.subtotal}>
                <Money value={data.subtotal} currency={currency} />
              </Row>
              <Row label={labels.sales.discounts}>
                <Money value={data.discount_total} currency={currency} />
              </Row>
              {showTax && (
                <Row label={labels.sales.taxes}>
                  <Money value={data.tax_total} currency={currency} />
                </Row>
              )}
              <div className="flex items-baseline justify-between border-t pt-3">
                <span className="font-semibold">{labels.sales.total}</span>
                <Money value={data.total} currency={currency} className="text-figure-sm" />
              </div>
              {data.status === "confirmed" && (
                <>
                  <Row label={labels.sales.paid}>
                    <Money value={data.paid_total} currency={currency} />
                  </Row>
                  <Row label={labels.sales.due}>
                    <Money value={data.balance} currency={currency} className="font-semibold" />
                  </Row>
                  {data.has_returns && (
                    <Row label={labels.sales.returned}>
                      <Money value={data.returned_total} currency={currency} />
                    </Row>
                  )}
                </>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardContent className="space-y-2 text-sm">
              <Row label={labels.sales.customer}>
                <span className="font-medium">{data.customer_name ?? labels.sales.anonymous}</span>
              </Row>
              <Row label={labels.sales.soldAt}>
                <span className="numeric">{formatDateTime(data.sold_at, timeZone)}</span>
              </Row>
              {data.confirmed_at && (
                <Row label={labels.sales.confirmedAt}>
                  <span className="numeric">{formatDateTime(data.confirmed_at, timeZone)}</span>
                </Row>
              )}
              {data.cancelled_at && (
                <>
                  <Row label={labels.sales.cancelledAt}>
                    <span className="numeric">{formatDateTime(data.cancelled_at, timeZone)}</span>
                  </Row>
                  <div className="rounded-md bg-destructive/5 p-3 text-danger-ink">
                    <p className="text-xs font-medium">{labels.sales.cancelReasonLabel}</p>
                    <p>{data.cancel_reason}</p>
                  </div>
                </>
              )}
            </CardContent>
          </Card>

          {data.debt && (
            <Card>
              <CardHeader>
                <CardTitle>{labels.sales.debt}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                <Row label={labels.sales.debtPrincipal}>
                  <Money value={data.debt.principal} currency={currency} />
                </Row>
                <Row label={labels.sales.debtPaid}>
                  <Money value={data.debt.amount_paid} currency={currency} />
                </Row>
                <Row label={labels.sales.debtBalance}>
                  <Money value={data.debt.balance} currency={currency} className="font-semibold" />
                </Row>
                <Row label={labels.sales.debtDue}>
                  <span className="numeric">{formatDate(data.debt.due_date, timeZone)}</span>
                </Row>
                <Badge variant={data.debt.status === "paid" ? "success" : "warning"}>
                  {labels.debtStatus[data.debt.status]}
                </Badge>
              </CardContent>
            </Card>
          )}
        </div>
      </div>

      <CancelDialog sale={data} open={cancelOpen} onOpenChange={setCancelOpen} />
    </>
  );
}

function CancelDialog({
  sale,
  open,
  onOpenChange,
}: {
  sale: SaleDetail;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  const cancel = useMutation({
    meta: { toastError: false },
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/sales/{sale_id}/cancel", {
          params: { path: { sale_id: sale.id } },
          body: { reason: reason.trim() },
        }),
      ),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.sales.detail(updated.id), updated);
      for (const key of [queryKeys.sales.all, queryKeys.stock.all, queryKeys.dashboard]) {
        void queryClient.invalidateQueries({ queryKey: key });
      }
      toast.success(labels.sales.cancelledToast(updated.sale_no));
      onOpenChange(false);
    },
    onError: (failure) => setError(errorMessage(failure)),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{labels.sales.cancelTitle}</DialogTitle>
          <DialogDescription>{labels.sales.cancelDescription}</DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (!reason.trim()) {
              setError(labels.validation.required);
              return;
            }
            setError(null);
            cancel.mutate();
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor="cancel-reason">{labels.sales.cancelReason}</Label>
            <Textarea
              id="cancel-reason"
              value={reason}
              maxLength={500}
              aria-invalid={Boolean(error)}
              aria-describedby={error ? "cancel-error" : undefined}
              onChange={(event) => setReason(event.target.value)}
            />
            <FieldError id="cancel-error" message={error} />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {labels.sales.cancelKeep}
            </Button>
            <Button type="submit" variant="destructive" disabled={cancel.isPending}>
              {labels.sales.cancelSubmit}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
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

function DetailSkeleton() {
  return (
    <div className="space-y-6">
      <Skeleton className="h-8 w-64" />
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <Skeleton className="h-72 w-full" />
        <Skeleton className="h-72 w-full" />
      </div>
    </div>
  );
}
