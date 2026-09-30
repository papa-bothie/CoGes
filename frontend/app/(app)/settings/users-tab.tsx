"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { DataTable, type Column } from "@/components/data-table";
import { ErrorState } from "@/components/error-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useCompanyLocale, useMe } from "@/hooks/use-me";
import { Can, usePermission } from "@/hooks/use-permission";
import { useTableParams } from "@/hooks/use-table-params";
import { api, unwrap } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { formatDateTime } from "@/lib/format";
import { labels } from "@/lib/labels";

import { CreateUserDialog, UserRolesDialog } from "./user-dialogs";

type User = Schemas["UserRead"];

export function useRoles() {
  return useQuery({
    queryKey: queryKeys.roles.all,
    queryFn: () => unwrap(api.GET("/api/v1/roles", { params: { query: { page_size: 100 } } })),
  });
}

/** Comptes de l'entreprise : rôles, activation (réversible, `PATCH is_active`, ADR 0054). */
export function UsersTab() {
  const queryClient = useQueryClient();
  const table = useTableParams();
  const { timeZone } = useCompanyLocale();
  const { data: me } = useMe();
  const canUpdate = usePermission("users:update");
  const canEditRoles = usePermission("roles:update");
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<User | null>(null);
  const roles = useRoles();
  const t = labels.settings.users;

  const params = { page: table.page, page_size: table.pageSize };
  const query = useQuery({
    queryKey: [...queryKeys.users.all, params],
    queryFn: () => unwrap(api.GET("/api/v1/users", { params: { query: params } })),
    placeholderData: keepPreviousData,
  });

  const toggle = useMutation({
    mutationFn: ({ id, active }: { id: string; active: boolean }) =>
      unwrap(
        api.PATCH("/api/v1/users/{user_id}", {
          params: { path: { user_id: id } },
          body: { is_active: active },
        }),
      ),
    onSuccess: (user) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.users.all });
      toast.success(user.is_active ? t.reactivated : t.deactivated);
    },
  });

  const columns: Column<User>[] = [
    {
      id: "name",
      header: t.columns.name,
      cell: (user) => (
        <span className="font-medium">
          {user.full_name}
          {user.id === me?.user.id && (
            <span className="ml-1 text-xs font-normal text-muted-foreground">({t.you})</span>
          )}
        </span>
      ),
    },
    { id: "email", header: t.columns.email, cell: (user) => user.email },
    {
      id: "roles",
      header: t.columns.roles,
      cell: (user) => (
        <span className="flex flex-wrap gap-1">
          {(user.roles ?? []).map((role) => (
            <Badge key={role.id} variant={role.is_system ? "info" : "neutral"}>
              {role.description ?? role.name}
            </Badge>
          ))}
        </span>
      ),
    },
    {
      id: "status",
      header: t.columns.status,
      cell: (user) => (
        <Badge variant={user.is_active ? "success" : "neutral"}>
          {user.is_active ? t.active : t.inactive}
        </Badge>
      ),
    },
    {
      id: "lastLogin",
      header: t.columns.lastLogin,
      cell: (user) => (
        <span className="numeric">
          {user.last_login_at ? formatDateTime(user.last_login_at, timeZone) : t.never}
        </span>
      ),
    },
    {
      id: "actions",
      header: t.columns.actions,
      className: "text-right",
      cell: (user) => (
        <span className="flex justify-end gap-1">
          {canEditRoles && roles.data && (
            <Button variant="outline" size="sm" onClick={() => setEditing(user)}>
              {t.editRoles}
            </Button>
          )}
          {canUpdate && user.id !== me?.user.id && (
            <Button
              variant="ghost"
              size="sm"
              disabled={toggle.isPending}
              onClick={() => toggle.mutate({ id: user.id, active: !user.is_active })}
            >
              {user.is_active ? t.deactivate : t.reactivate}
            </Button>
          )}
        </span>
      ),
    },
  ];

  return (
    <>
      {query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <DataTable
          caption={labels.settings.tabs.users}
          columns={columns}
          rows={query.data?.items}
          rowKey={(user) => user.id}
          total={query.data?.total ?? 0}
          page={table.page}
          pageSize={table.pageSize}
          onPageChange={table.setPage}
          loading={query.isFetching}
          rowClassName={(user) => (user.is_active ? undefined : "text-muted-foreground")}
          empty={t.empty}
          filters={
            <div className="flex w-full items-center justify-between gap-2">
              <span className="text-sm text-muted-foreground">
                {query.data ? t.count(query.data.total) : null}
              </span>
              <Can permission="users:create">
                <Button onClick={() => setCreating(true)} disabled={!roles.data}>
                  <Plus aria-hidden />
                  {t.add}
                </Button>
              </Can>
            </div>
          }
        />
      )}
      <CreateUserDialog
        open={creating}
        onOpenChange={setCreating}
        roles={roles.data?.items ?? []}
      />
      {editing && roles.data && (
        <UserRolesDialog
          key={editing.id}
          user={editing}
          roles={roles.data.items}
          onClose={() => setEditing(null)}
        />
      )}
    </>
  );
}
