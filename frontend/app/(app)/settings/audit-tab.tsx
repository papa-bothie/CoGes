"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { DataTable, type Column } from "@/components/data-table";
import { ErrorState } from "@/components/error-state";
import { PeriodPicker } from "@/components/period/period-picker";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useCompanyLocale } from "@/hooks/use-me";
import { usePeriod } from "@/hooks/use-period";
import { usePermission } from "@/hooks/use-permission";
import { useTableParams } from "@/hooks/use-table-params";
import { api, unwrap } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { formatDateTime } from "@/lib/format";
import { labels } from "@/lib/labels";
import { AUDIT_ENTITIES, entityLabel } from "@/lib/permission-labels";

type Log = Schemas["AuditLogRead"];
type Action = Log["action"];

const ALL = "all";
const ACTIONS = Object.keys(labels.settings.audit.actions) as Action[];
const ACTION_VARIANTS: Partial<
  Record<Action, "info" | "warning" | "danger" | "neutral" | "success">
> = {
  insert: "success",
  update: "info",
  delete: "danger",
  cancel: "warning",
  confirm: "info",
};

/** Journal d'activité (`GET /audit-logs`, ADR 0053) : critique et secondaire, en lecture. */
export function AuditTab() {
  const table = useTableParams();
  const period = usePeriod();
  const { timeZone } = useCompanyLocale();
  const canListUsers = usePermission("users:read");
  const [open, setOpen] = useState<Log | null>(null);
  const t = labels.settings.audit;

  const actor = table.get("actor");
  const action = table.get("action") as Action | null;
  const entity = table.get("entity");
  const params = {
    page: table.page,
    page_size: table.pageSize,
    actor_user_id: actor ?? undefined,
    action: action ?? undefined,
    entity_table: entity ?? undefined,
    from: period.fromIso ?? undefined,
    to: period.toIso ?? undefined,
  };
  const query = useQuery({
    queryKey: queryKeys.audit.list(params),
    queryFn: () => unwrap(api.GET("/api/v1/audit-logs", { params: { query: params } })),
    placeholderData: keepPreviousData,
  });
  const users = useQuery({
    queryKey: [...queryKeys.users.all, { page_size: 100 }],
    queryFn: () => unwrap(api.GET("/api/v1/users", { params: { query: { page_size: 100 } } })),
    enabled: canListUsers,
  });

  const columns: Column<Log>[] = [
    {
      id: "date",
      header: t.columns.date,
      cell: (log) => (
        <span className="numeric whitespace-nowrap">
          {formatDateTime(log.occurred_at, timeZone)}
        </span>
      ),
    },
    {
      id: "user",
      header: t.columns.user,
      cell: (log) => log.actor_name ?? <span className="text-muted-foreground">{t.system}</span>,
    },
    {
      id: "action",
      header: t.columns.action,
      cell: (log) => (
        <Badge variant={ACTION_VARIANTS[log.action] ?? "neutral"}>{t.actions[log.action]}</Badge>
      ),
    },
    {
      id: "entity",
      header: t.columns.entity,
      cell: (log) => (
        <span>
          {entityLabel(log.entity_table)}
          {log.entity_id && (
            <span className="ml-2 text-xs numeric text-muted-foreground">
              {log.entity_id.slice(0, 8)}
            </span>
          )}
        </span>
      ),
    },
    {
      id: "ip",
      header: t.columns.ip,
      cell: (log) => <span className="numeric text-muted-foreground">{log.ip_address ?? "—"}</span>,
    },
    {
      id: "detail",
      header: t.columns.detail,
      className: "text-right",
      cell: (log) => (
        <Button variant="ghost" size="sm" onClick={() => setOpen(log)}>
          {t.see}
        </Button>
      ),
    },
  ];

  const filter = (key: string, value: string) => table.setFilter(key, value === ALL ? null : value);

  return (
    <>
      {query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <DataTable
          caption={labels.settings.tabs.audit}
          columns={columns}
          rows={query.data?.items}
          rowKey={(log) => String(log.id)}
          total={query.data?.total ?? 0}
          page={table.page}
          pageSize={table.pageSize}
          onPageChange={table.setPage}
          loading={query.isFetching}
          onRowClick={setOpen}
          empty={t.empty}
          filters={
            <div className="flex w-full flex-wrap items-center gap-2">
              <PeriodPicker />
              {canListUsers && (
                <Select value={actor ?? ALL} onValueChange={(value) => filter("actor", value)}>
                  <SelectTrigger aria-label={t.userFilter} className="w-52">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={ALL}>{t.allUsers}</SelectItem>
                    {users.data?.items.map((user) => (
                      <SelectItem key={user.id} value={user.id}>
                        {user.full_name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
              <Select value={action ?? ALL} onValueChange={(value) => filter("action", value)}>
                <SelectTrigger aria-label={t.actionFilter} className="w-44">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>{t.allActions}</SelectItem>
                  {ACTIONS.map((value) => (
                    <SelectItem key={value} value={value}>
                      {t.actions[value]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select value={entity ?? ALL} onValueChange={(value) => filter("entity", value)}>
                <SelectTrigger aria-label={t.entityFilter} className="w-52">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>{t.allEntities}</SelectItem>
                  {Object.entries(AUDIT_ENTITIES).map(([value, label]) => (
                    <SelectItem key={value} value={value}>
                      {label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <span className="ml-auto text-sm text-muted-foreground">
                {query.data ? t.count(query.data.total) : null}
              </span>
            </div>
          }
        />
      )}
      <DiffDialog log={open} onClose={() => setOpen(null)} />
    </>
  );
}

function show(value: unknown): string {
  if (value === undefined) return "—";
  if (value === null) return "∅";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

/** Avant / après, champ par champ, tels que l'audit les a écrits (aucune interprétation). */
function DiffDialog({ log, onClose }: { log: Log | null; onClose: () => void }) {
  const { timeZone } = useCompanyLocale();
  const t = labels.settings.audit;
  const diff = (log?.diff ?? {}) as {
    before?: Record<string, unknown> | null;
    after?: Record<string, unknown> | null;
  };
  const before = diff.before ?? {};
  const after = diff.after ?? {};
  const keys = [...new Set([...Object.keys(before), ...Object.keys(after)])];

  return (
    <Dialog open={log !== null} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="sm:max-w-2xl">
        {log && (
          <>
            <DialogHeader>
              <DialogTitle>
                {t.diffTitle(
                  entityLabel(log.entity_table),
                  formatDateTime(log.occurred_at, timeZone),
                )}
              </DialogTitle>
              <DialogDescription>
                {t.actions[log.action]} · {log.actor_name ?? t.system}
                {log.entity_id ? ` · ${log.entity_id}` : ""}
              </DialogDescription>
            </DialogHeader>
            {keys.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t.noDiff}</p>
            ) : (
              <div className="max-h-[60vh] overflow-auto rounded-lg border">
                <table className="w-full table-fixed text-sm">
                  <colgroup>
                    <col className="w-1/4" />
                    <col className="w-[37.5%]" />
                    <col className="w-[37.5%]" />
                  </colgroup>
                  <thead className="sticky top-0 bg-card">
                    <tr className="border-b text-left">
                      <th className="px-3 py-2 font-medium">{t.field}</th>
                      <th className="px-3 py-2 font-medium">{t.before}</th>
                      <th className="px-3 py-2 font-medium">{t.after}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {keys.map((key) => {
                      const changed = show(before[key]) !== show(after[key]);
                      return (
                        <tr key={key} className={changed ? "border-b bg-warning/5" : "border-b"}>
                          <td className="px-3 py-1.5 font-medium break-all">{key}</td>
                          <td className="px-3 py-1.5 break-all tabular-nums text-muted-foreground">
                            {show(before[key])}
                          </td>
                          <td className="px-3 py-1.5 break-all tabular-nums">{show(after[key])}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
