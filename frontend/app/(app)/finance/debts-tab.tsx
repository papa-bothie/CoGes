"use client";

import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { ErrorState } from "@/components/error-state";
import { Chip } from "@/components/kit/chip";
import { FilterChips, MoreButton, OUTLINE_ACTION } from "@/components/kit/filter-chips";
import { Avatar, ListRow } from "@/components/kit/list-row";
import { StatusPill } from "@/components/kit/status-pill";
import { ReasonDialog } from "@/components/reason-dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { useCompanyLocale } from "@/hooks/use-me";
import { Can, usePermission } from "@/hooks/use-permission";
import { useTableParams } from "@/hooks/use-table-params";
import { api, unwrap } from "@/lib/api/client";
import { MONEY_KEYS, queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { formatAmount, formatDate } from "@/lib/format";
import { labels } from "@/lib/labels";
import { todayIn } from "@/lib/period";
import { cn } from "@/lib/utils";

import { SettleDialog } from "./settle-dialog";
import { SupplierDebtDialog } from "./supplier-debt-dialog";

type Debt = Schemas["DebtDetail"];
type DebtStatus = Schemas["DebtStatus"];
type PartyType = Schemas["PartyType"];

const STATUSES: readonly DebtStatus[] = ["open", "partially_paid", "paid", "written_off"];
const t = labels.finance.debts;

function isOpen(debt: Debt) {
  return debt.status === "open" || debt.status === "partially_paid";
}

/**
 * « Toutes les dettes » (ADR 0073), dans le style de la maquette v2 : puces de filtre, une
 * ligne par dette avec son reste en pastille, « Régler » et « Abandonner » (gérant) en
 * boutons de 48 px. Une dette ouverte dont l'échéance est passée le dit en rouge.
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
  const today = todayIn(timeZone);

  const party = table.get("party") as PartyType | null;
  const status = table.get("status") as DebtStatus | null;
  const overdue = table.get("overdue") === "1";
  const filters = {
    page_size: table.pageSize,
    party_type: party ?? undefined,
    status: status ?? undefined,
    overdue: overdue || undefined,
  };
  const query = useInfiniteQuery({
    queryKey: queryKeys.debts.list({ ...filters, infinite: true }),
    initialPageParam: 1,
    queryFn: ({ pageParam }) =>
      unwrap(api.GET("/api/v1/debts", { params: { query: { ...filters, page: pageParam } } })),
    getNextPageParam: (last) =>
      last.page * last.page_size < last.total ? last.page + 1 : undefined,
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

  const debts = query.data?.pages.flatMap((page) => page.items) ?? [];
  const total = query.data?.pages[0]?.total;
  const isOverdue = (debt: Debt) => isOpen(debt) && debt.due_date !== null && debt.due_date < today;

  return (
    <>
      <div className="flex flex-col gap-3">
        <FilterChips
          label={t.partyFilter}
          value={party}
          allLabel={t.allParties}
          options={[
            ["customer", t.party.customer],
            ["supplier", t.party.supplier],
          ]}
          onChange={(next) => table.setFilter("party", next)}
        />
        <FilterChips
          label={t.statusFilter}
          value={status}
          allLabel={t.allStatuses}
          options={STATUSES.map((value) => [value, labels.debtStatus[value]] as const)}
          onChange={(next) => table.setFilter("status", next)}
        />
        <div className="flex flex-wrap items-center gap-2">
          <Chip
            selected={overdue}
            rubrique="depenses"
            onClick={() => table.setFilter("overdue", overdue ? null : "1")}
          >
            {t.overdueOnly}
          </Chip>
          <span className="ml-auto text-muted-foreground">
            {total !== undefined ? t.count(total) : null}
          </span>
          <Can permission="debts:create">
            <button type="button" className={OUTLINE_ACTION} onClick={() => setCreating(true)}>
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
        ) : debts.length === 0 ? (
          <p className="py-carte text-muted-foreground">{t.empty}</p>
        ) : (
          <ul aria-label={labels.moneyScreens.allDebts} className="[&>li:first-child>*]:border-t-0">
            {debts.map((debt) => {
              const name = debt.party_name ?? t.deletedParty;
              const href = debt.customer_id
                ? `/customers/${debt.customer_id}`
                : debt.supplier_id
                  ? `/suppliers/${debt.supplier_id}`
                  : null;
              const late = isOverdue(debt);
              const pill =
                debt.status === "paid" ? (
                  <StatusPill status="paid" />
                ) : debt.status === "written_off" ? (
                  <StatusPill status="writtenOff" />
                ) : (
                  <StatusPill status="remaining" amount={formatAmount(debt.balance, currency)} />
                );
              return (
                <li key={debt.id}>
                  <ListRow
                    wrap
                    className="flex-wrap"
                    leading={
                      <Avatar
                        name={debt.party_name ?? null}
                        rubrique={debt.party_type === "customer" ? "clients" : "argent"}
                      />
                    }
                    title={
                      href && debt.party_name ? (
                        <Link
                          href={href}
                          className="inline-flex min-h-11 items-center hover:underline pointer-coarse:min-h-12"
                        >
                          {name}
                        </Link>
                      ) : (
                        name
                      )
                    }
                    subtitle={
                      <>
                        {t.partyType[debt.party_type]} {formatAmount(debt.principal, currency)} ·{" "}
                        {t.columns.created.toLowerCase()}{" "}
                        <span className="numeric">{formatDate(debt.created_at, timeZone)}</span>
                        {debt.due_date && (
                          <>
                            {" · "}
                            <span
                              className={cn("tabular-nums", late && "font-bold text-destructive")}
                            >
                              {t.columns.due.toLowerCase()} {formatDate(debt.due_date, timeZone)}
                              {late && ` (${t.overdue.toLowerCase()})`}
                            </span>
                          </>
                        )}
                      </>
                    }
                    trailing={
                      <>
                        {pill}
                        {isOpen(debt) && canSettle && (
                          <button
                            type="button"
                            className={OUTLINE_ACTION}
                            onClick={() => setSettling(debt)}
                          >
                            {t.settle}
                          </button>
                        )}
                        {isOpen(debt) && canWriteOff && debt.party_type === "customer" && (
                          <button
                            type="button"
                            className={cn(OUTLINE_ACTION, "border-transparent bg-transparent")}
                            onClick={() => setWritingOff(debt)}
                          >
                            {t.writeOff}
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
