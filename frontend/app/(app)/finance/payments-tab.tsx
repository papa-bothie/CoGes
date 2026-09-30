"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { DataTable, type Column } from "@/components/data-table";
import { ErrorState } from "@/components/error-state";
import { Money } from "@/components/money";
import { ReasonDialog } from "@/components/reason-dialog";
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
import { useIdempotencyKey } from "@/lib/api/idempotency";
import { MONEY_KEYS, queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { formatDateTime } from "@/lib/format";
import { labels } from "@/lib/labels";

import { PaymentDialog } from "./payment-dialog";

type Payment = Schemas["PaymentDetail"];
type Direction = Schemas["CashDirection"];

const ALL = "all";

function PaymentContext({ payment }: { payment: Payment }) {
  const t = labels.finance.payments.context;
  if (payment.reversal_of_payment_id) return <>{t.reversal}</>;
  if (payment.sale_id)
    return (
      <Link href={`/sales/${payment.sale_id}`} className="text-primary hover:underline">
        {t.sale}
      </Link>
    );
  if (payment.sale_return_id)
    return (
      <Link
        href={`/sales/returns/${payment.sale_return_id}`}
        className="text-primary hover:underline"
      >
        {t.saleReturn}
      </Link>
    );
  if (payment.expense_id) return <>{t.expense}</>;
  if (payment.allocations.length > 0) return <>{t.debts(payment.allocations.length)}</>;
  return <span className="text-muted-foreground">{t.free}</span>;
}

/** Mouvements de caisse de la période (`GET /payments`), annulation par contre-écriture. */
export function PaymentsTab() {
  const queryClient = useQueryClient();
  const table = useTableParams();
  const period = usePeriod();
  const { timeZone, currency } = useCompanyLocale();
  const canCancel = usePermission("payments:cancel");
  const cancelKey = useIdempotencyKey();
  const [creating, setCreating] = useState(false);
  const [cancelling, setCancelling] = useState<Payment | null>(null);
  const t = labels.finance.payments;

  const direction = table.get("direction") as Direction | null;
  const params = {
    page: table.page,
    page_size: table.pageSize,
    direction: direction ?? undefined,
    from: period.fromIso ?? undefined,
    to: period.toIso ?? undefined,
  };
  const query = useQuery({
    queryKey: queryKeys.payments.list(params),
    queryFn: () => unwrap(api.GET("/api/v1/payments", { params: { query: params } })),
    placeholderData: keepPreviousData,
  });

  const cancel = useMutation({
    meta: { toastError: false },
    mutationFn: ({ id, reason }: { id: string; reason: string }) =>
      unwrap(
        api.POST("/api/v1/payments/{payment_id}/cancel", {
          params: { path: { payment_id: id } },
          body: { reason },
          headers: cancelKey.headers,
        }),
      ),
    onSuccess: () => {
      cancelKey.renew();
      for (const key of MONEY_KEYS) void queryClient.invalidateQueries({ queryKey: key });
      toast.success(t.cancelledToast);
    },
  });

  const columns: Column<Payment>[] = [
    {
      id: "date",
      header: t.columns.date,
      cell: (payment) => (
        <span className="numeric whitespace-nowrap">
          {formatDateTime(payment.paid_at, timeZone)}
        </span>
      ),
    },
    {
      id: "direction",
      header: t.columns.direction,
      cell: (payment) => (
        <Badge variant={payment.direction === "inflow" ? "success" : "neutral"}>
          {t.direction[payment.direction]}
        </Badge>
      ),
    },
    {
      id: "method",
      header: t.columns.method,
      cell: (payment) => labels.paymentMethods[payment.method],
    },
    {
      id: "context",
      header: t.columns.context,
      cell: (payment) => <PaymentContext payment={payment} />,
    },
    {
      id: "reference",
      header: t.columns.reference,
      cell: (payment) => payment.reference ?? <span className="text-muted-foreground">—</span>,
    },
    {
      id: "amount",
      header: t.columns.amount,
      numeric: true,
      cell: (payment) => (
        <Money
          value={payment.amount}
          currency={currency}
          className={
            payment.cancelled || payment.reversal_of_payment_id
              ? "text-muted-foreground line-through"
              : "font-medium"
          }
        />
      ),
    },
    {
      id: "status",
      header: t.columns.status,
      cell: (payment) =>
        payment.reversal_of_payment_id ? (
          <Badge variant="neutral">{t.reversal}</Badge>
        ) : payment.cancelled ? (
          <Badge variant="danger">{t.cancelled}</Badge>
        ) : canCancel ? (
          <Button
            variant="ghost"
            size="sm"
            className="text-muted-foreground"
            onClick={() => setCancelling(payment)}
          >
            {t.cancel}
          </Button>
        ) : null,
    },
  ];

  return (
    <>
      {query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <DataTable
          caption={labels.finance.tabs.payments}
          columns={columns}
          rows={query.data?.items}
          rowKey={(payment) => payment.id}
          total={query.data?.total ?? 0}
          page={table.page}
          pageSize={table.pageSize}
          onPageChange={table.setPage}
          loading={query.isFetching}
          empty={t.empty}
          filters={
            <div className="flex w-full flex-wrap items-center justify-between gap-2">
              <Select
                value={direction ?? ALL}
                onValueChange={(value) =>
                  table.setFilter("direction", value === ALL ? null : value)
                }
              >
                <SelectTrigger aria-label={t.directionFilter} className="w-48">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>{t.allDirections}</SelectItem>
                  <SelectItem value="inflow">{t.direction.inflow}</SelectItem>
                  <SelectItem value="outflow">{t.direction.outflow}</SelectItem>
                </SelectContent>
              </Select>
              <span className="text-sm text-muted-foreground">
                {query.data ? t.count(query.data.total) : null}
              </span>
              <Can permission="payments:create">
                <Button onClick={() => setCreating(true)}>
                  <Plus aria-hidden />
                  {t.record}
                </Button>
              </Can>
            </div>
          }
        />
      )}
      <PaymentDialog open={creating} onOpenChange={setCreating} />
      <ReasonDialog
        open={cancelling !== null}
        onOpenChange={(open) => !open && setCancelling(null)}
        title={t.cancelTitle}
        description={t.cancelDescription}
        reasonLabel={t.cancelReason}
        submitLabel={t.cancelSubmit}
        pending={cancel.isPending}
        onSubmit={(reason) => cancel.mutateAsync({ id: cancelling!.id, reason })}
      />
    </>
  );
}
