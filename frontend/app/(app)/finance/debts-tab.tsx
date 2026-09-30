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
import { Can, usePermission } from "@/hooks/use-permission";
import { useTableParams } from "@/hooks/use-table-params";
import { api, unwrap } from "@/lib/api/client";
import { MONEY_KEYS, queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { formatDate } from "@/lib/format";
import { labels } from "@/lib/labels";
import { todayIn } from "@/lib/period";

import { SettleDialog } from "./settle-dialog";
import { SupplierDebtDialog } from "./supplier-debt-dialog";

type Debt = Schemas["DebtDetail"];
type DebtStatus = Schemas["DebtStatus"];
type PartyType = Schemas["PartyType"];

const ALL = "all";
const STATUSES: readonly DebtStatus[] = ["open", "partially_paid", "paid", "written_off"];
const VARIANTS: Record<DebtStatus, "warning" | "success" | "neutral"> = {
  open: "warning",
  partially_paid: "warning",
  paid: "success",
  written_off: "neutral",
};

function isOpen(debt: Debt) {
  return debt.status === "open" || debt.status === "partially_paid";
}

/**
 * Créances clients et dettes fournisseurs (`GET /debts`), échéance la plus proche en tête.
 * Une dette ouverte dont l'échéance est passée est surlignée ; « Régler » répartit un
 * versement sur les dettes du même tiers ; « Abandonner » est réservé au gérant.
 */
export function DebtsTab() {
  const queryClient = useQueryClient();
  const table = useTableParams();
  const { timeZone, currency } = useCompanyLocale();
  const canSettle = usePermission("payments:create");
  const canWriteOff = usePermission("debts:write_off");
  const [settling, setSettling] = useState<Debt | null>(null);
  const [writingOff, setWritingOff] = useState<Debt | null>(null);
  const [creating, setCreating] = useState(false);
  const t = labels.finance.debts;
  const today = todayIn(timeZone);

  const party = table.get("party") as PartyType | null;
  const status = table.get("status") as DebtStatus | null;
  const overdue = table.get("overdue") === "1";
  const params = {
    page: table.page,
    page_size: table.pageSize,
    party_type: party ?? undefined,
    status: status ?? undefined,
    overdue: overdue || undefined,
  };
  const query = useQuery({
    queryKey: queryKeys.debts.list(params),
    queryFn: () => unwrap(api.GET("/api/v1/debts", { params: { query: params } })),
    placeholderData: keepPreviousData,
  });

  const writeOff = useMutation({
    meta: { toastError: false },
    mutationFn: ({ id, reason }: { id: string; reason: string }) =>
      unwrap(
        api.POST("/api/v1/debts/{debt_id}/write-off", {
          params: { path: { debt_id: id } },
          body: { reason },
        }),
      ),
    onSuccess: () => {
      for (const key of MONEY_KEYS) void queryClient.invalidateQueries({ queryKey: key });
      toast.success(t.writtenOff);
    },
  });

  const isOverdue = (debt: Debt) => isOpen(debt) && debt.due_date !== null && debt.due_date < today;

  const columns: Column<Debt>[] = [
    {
      id: "party",
      header: t.columns.party,
      cell: (debt) => {
        const href = debt.customer_id
          ? `/customers/${debt.customer_id}`
          : debt.supplier_id
            ? `/suppliers/${debt.supplier_id}`
            : null;
        const name = debt.party_name ?? t.deletedParty;
        return href && debt.party_name ? (
          <Link href={href} className="font-medium hover:underline">
            {name}
          </Link>
        ) : (
          <span className="text-muted-foreground">{name}</span>
        );
      },
    },
    { id: "type", header: t.columns.type, cell: (debt) => t.partyType[debt.party_type] },
    {
      id: "created",
      header: t.columns.created,
      cell: (debt) =>
        debt.sale_id ? (
          <Link href={`/sales/${debt.sale_id}`} className="numeric hover:underline">
            {formatDate(debt.created_at, timeZone)}
          </Link>
        ) : (
          <span className="numeric">{formatDate(debt.created_at, timeZone)}</span>
        ),
    },
    {
      id: "principal",
      header: t.columns.principal,
      numeric: true,
      cell: (debt) => <Money value={debt.principal} currency={currency} />,
    },
    {
      id: "paid",
      header: t.columns.paid,
      numeric: true,
      cell: (debt) => <Money value={debt.amount_paid} currency={currency} />,
    },
    {
      id: "balance",
      header: t.columns.balance,
      numeric: true,
      cell: (debt) => <Money value={debt.balance} currency={currency} className="font-medium" />,
    },
    {
      id: "due",
      header: t.columns.due,
      cell: (debt) => (
        <span className="flex items-center gap-2 whitespace-nowrap">
          <span className="numeric">{formatDate(debt.due_date, timeZone)}</span>
          {isOverdue(debt) && <Badge variant="danger">{t.overdue}</Badge>}
        </span>
      ),
    },
    {
      id: "status",
      header: t.columns.status,
      cell: (debt) => (
        <Badge variant={VARIANTS[debt.status]}>{labels.debtStatus[debt.status]}</Badge>
      ),
    },
    {
      id: "actions",
      header: t.columns.actions,
      className: "text-right",
      cell: (debt) =>
        isOpen(debt) ? (
          <div className="flex justify-end gap-1">
            {canSettle && (
              <Button variant="outline" size="sm" onClick={() => setSettling(debt)}>
                {t.settle}
              </Button>
            )}
            {canWriteOff && debt.party_type === "customer" && (
              <Button variant="ghost" size="sm" onClick={() => setWritingOff(debt)}>
                {t.writeOff}
              </Button>
            )}
          </div>
        ) : null,
    },
  ];

  return (
    <>
      {query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <DataTable
          caption={labels.finance.tabs.debts}
          columns={columns}
          rows={query.data?.items}
          rowKey={(debt) => debt.id}
          total={query.data?.total ?? 0}
          page={table.page}
          pageSize={table.pageSize}
          onPageChange={table.setPage}
          loading={query.isFetching}
          rowClassName={(debt) => (isOverdue(debt) ? "bg-destructive/5" : undefined)}
          empty={t.empty}
          filters={
            <div className="flex w-full flex-wrap items-center gap-2">
              <Select
                value={party ?? ALL}
                onValueChange={(value) => table.setFilter("party", value === ALL ? null : value)}
              >
                <SelectTrigger aria-label={t.partyFilter} className="w-52">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>{t.allParties}</SelectItem>
                  <SelectItem value="customer">{t.party.customer}</SelectItem>
                  <SelectItem value="supplier">{t.party.supplier}</SelectItem>
                </SelectContent>
              </Select>
              <Select
                value={status ?? ALL}
                onValueChange={(value) => table.setFilter("status", value === ALL ? null : value)}
              >
                <SelectTrigger aria-label={t.statusFilter} className="w-48">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>{t.allStatuses}</SelectItem>
                  {STATUSES.map((value) => (
                    <SelectItem key={value} value={value}>
                      {labels.debtStatus[value]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  className="size-4 accent-primary"
                  checked={overdue}
                  onChange={(event) =>
                    table.setFilter("overdue", event.target.checked ? "1" : null)
                  }
                />
                {t.overdueOnly}
              </label>
              <span className="ml-auto text-sm text-muted-foreground">
                {query.data ? t.count(query.data.total) : null}
              </span>
              <Can permission="debts:create">
                <Button variant="outline" onClick={() => setCreating(true)}>
                  <Plus aria-hidden />
                  {t.add}
                </Button>
              </Can>
            </div>
          }
        />
      )}
      {settling && (
        <SettleDialog key={settling.id} debt={settling} onClose={() => setSettling(null)} />
      )}
      <SupplierDebtDialog open={creating} onOpenChange={setCreating} />
      <ReasonDialog
        open={writingOff !== null}
        onOpenChange={(open) => !open && setWritingOff(null)}
        title={t.writeOffTitle}
        description={t.writeOffDescription}
        reasonLabel={t.writeOffReason}
        submitLabel={t.writeOffSubmit}
        pending={writeOff.isPending}
        onSubmit={(reason) => writeOff.mutateAsync({ id: writingOff!.id, reason })}
      />
    </>
  );
}
