"use client";

import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Loader2, Minus, Plus, Trash2 } from "lucide-react";
import { Fragment, useState } from "react";
import { toast } from "sonner";

import { ErrorState } from "@/components/error-state";
import { FieldError } from "@/components/field-error";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Can, usePermission } from "@/hooks/use-permission";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { labels } from "@/lib/labels";
import { ACTION_LABELS, resourceLabel } from "@/lib/permission-labels";
import { cn } from "@/lib/utils";

import { useRoles } from "./users-tab";

type Permission = Schemas["PermissionRead"];
type Role = Schemas["RoleRead"];

function groupByResource(permissions: readonly Permission[]) {
  const groups = new Map<string, Permission[]>();
  for (const permission of [...permissions].sort((a, b) => a.code.localeCompare(b.code))) {
    groups.set(permission.resource, [...(groups.get(permission.resource) ?? []), permission]);
  }
  return [...groups.entries()].sort(([a], [b]) => resourceLabel(a).localeCompare(resourceLabel(b)));
}

/**
 * Matrice permissions × rôles. Les rôles système sont en lecture (le serveur refuse de les
 * modifier) ; un rôle personnalisé se coche puis s'enregistre, colonne par colonne.
 */
export function RolesTab() {
  const queryClient = useQueryClient();
  const canUpdate = usePermission("roles:update");
  const canDelete = usePermission("roles:delete");
  const roles = useRoles();
  const permissions = useQuery({
    queryKey: queryKeys.permissions,
    queryFn: () => unwrap(api.GET("/api/v1/permissions")),
  });
  const roleItems = roles.data?.items ?? [];
  const details = useQueries({
    queries: roleItems.map((role) => ({
      queryKey: queryKeys.roles.detail(role.id),
      queryFn: () =>
        unwrap(api.GET("/api/v1/roles/{role_id}", { params: { path: { role_id: role.id } } })),
    })),
  });
  const [drafts, setDrafts] = useState<Record<string, Set<string>>>({});
  const [creating, setCreating] = useState(false);
  const [removing, setRemoving] = useState<Role | null>(null);
  const t = labels.settings.roles;

  const granted = (roleId: string): Set<string> | undefined => {
    if (drafts[roleId]) return drafts[roleId];
    const detail = details.find((query) => query.data?.id === roleId)?.data;
    return detail ? new Set(detail.permissions) : undefined;
  };

  const save = useMutation({
    mutationFn: ({ roleId, codes }: { roleId: string; codes: string[] }) =>
      unwrap(
        api.PATCH("/api/v1/roles/{role_id}", {
          params: { path: { role_id: roleId } },
          body: { permissions: codes },
        }),
      ),
    onSuccess: (_role, { roleId }) => {
      setDrafts((all) => Object.fromEntries(Object.entries(all).filter(([id]) => id !== roleId)));
      void queryClient.invalidateQueries({ queryKey: queryKeys.roles.all });
      toast.success(t.saved);
    },
  });

  const remove = useMutation({
    mutationFn: (roleId: string) =>
      unwrap(api.DELETE("/api/v1/roles/{role_id}", { params: { path: { role_id: roleId } } })),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.roles.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.users.all });
      setRemoving(null);
      toast.success(t.removed);
    },
  });

  if (roles.isError || permissions.isError) {
    return (
      <ErrorState
        error={roles.error ?? permissions.error}
        onRetry={() => {
          void roles.refetch();
          void permissions.refetch();
        }}
      />
    );
  }
  if (!roles.data || !permissions.data || details.some((query) => query.isPending)) {
    return <Skeleton className="h-[480px] w-full" />;
  }

  const toggle = (role: Role, code: string) => {
    const current = new Set(granted(role.id));
    if (current.has(code)) current.delete(code);
    else current.add(code);
    setDrafts((all) => ({ ...all, [role.id]: current }));
  };

  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
        <div>
          <CardTitle>{t.matrix}</CardTitle>
          <CardDescription>{t.matrixHint}</CardDescription>
        </div>
        <Can permission="roles:create">
          <Button variant="outline" onClick={() => setCreating(true)}>
            <Plus aria-hidden />
            {t.add}
          </Button>
        </Can>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-sm">
            <caption className="sr-only">{t.matrix}</caption>
            <thead className="sticky top-0 bg-card">
              <tr className="border-b">
                <th scope="col" className="px-4 py-2 text-left font-medium">
                  {t.permission}
                </th>
                {roleItems.map((role) => {
                  const dirty = Boolean(drafts[role.id]);
                  return (
                    <th
                      key={role.id}
                      scope="col"
                      className="min-w-32 px-3 py-2 text-center font-medium"
                    >
                      <span className="block">{role.description ?? role.name}</span>
                      <Badge variant={role.is_system ? "info" : "neutral"} className="mt-1">
                        {role.is_system ? t.system : t.custom}
                      </Badge>
                      {!role.is_system && (
                        <span className="mt-1 flex justify-center gap-1">
                          {canUpdate && dirty && (
                            <Button
                              size="sm"
                              disabled={save.isPending}
                              onClick={() =>
                                save.mutate({
                                  roleId: role.id,
                                  codes: [...(granted(role.id) ?? [])],
                                })
                              }
                            >
                              {save.isPending && <Loader2 className="animate-spin" aria-hidden />}
                              {t.save}
                            </Button>
                          )}
                          {canDelete && (
                            <Button
                              variant="ghost"
                              size="icon-sm"
                              aria-label={t.removeTitle(role.description ?? role.name)}
                              onClick={() => setRemoving(role)}
                            >
                              <Trash2 />
                            </Button>
                          )}
                        </span>
                      )}
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {groupByResource(permissions.data).map(([resource, items]) => (
                <Fragment key={resource}>
                  <tr className="border-b bg-muted/40">
                    <th
                      scope="rowgroup"
                      colSpan={roleItems.length + 1}
                      className="px-4 py-1.5 text-left text-xs font-semibold tracking-wide text-muted-foreground uppercase"
                    >
                      {resourceLabel(resource)}
                    </th>
                  </tr>
                  {items.map((permission) => (
                    <tr key={permission.code} className="border-b last:border-0">
                      <th scope="row" className="px-4 py-1.5 text-left font-normal">
                        {ACTION_LABELS[permission.action] ?? permission.action}
                        <span className="ml-2 text-xs numeric text-muted-foreground">
                          {permission.code}
                        </span>
                      </th>
                      {roleItems.map((role) => {
                        const has = granted(role.id)?.has(permission.code) ?? false;
                        const editable = canUpdate && !role.is_system;
                        const name = t.granted(permission.code, role.description ?? role.name);
                        return (
                          <td key={role.id} className="px-3 py-1.5 text-center">
                            {editable ? (
                              <input
                                type="checkbox"
                                aria-label={name}
                                className="size-4 accent-primary"
                                checked={has}
                                onChange={() => toggle(role, permission.code)}
                              />
                            ) : has ? (
                              <Check
                                className="mx-auto size-4 text-success-ink"
                                aria-label={name}
                              />
                            ) : (
                              <Minus
                                className={cn("mx-auto size-4 text-muted-foreground/40")}
                                aria-hidden
                              />
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
      <CreateRoleDialog open={creating} onOpenChange={setCreating} />
      <Dialog open={removing !== null} onOpenChange={(open) => !open && setRemoving(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>
              {removing && t.removeTitle(removing.description ?? removing.name)}
            </DialogTitle>
            <DialogDescription>{t.removeBody}</DialogDescription>
          </DialogHeader>
          <FieldError message={remove.error ? errorMessage(remove.error) : null} />
          <DialogFooter>
            <Button variant="outline" onClick={() => setRemoving(null)}>
              {labels.common.cancel}
            </Button>
            <Button
              variant="destructive"
              disabled={remove.isPending}
              onClick={() => removing && remove.mutate(removing.id)}
            >
              {t.remove}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}

function CreateRoleDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const t = labels.settings.roles;

  const create = useMutation({
    meta: { toastError: false },
    mutationFn: (body: Schemas["RoleCreate"]) => unwrap(api.POST("/api/v1/roles", { body })),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.roles.all });
      toast.success(t.created);
      setName("");
      setDescription("");
      setError(null);
      onOpenChange(false);
    },
    onError: (caught) => setError(errorMessage(caught)),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t.createTitle}</DialogTitle>
        </DialogHeader>
        <form
          className="space-y-4"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            if (!/^[a-z0-9][a-z0-9_-]{0,63}$/.test(name.trim())) {
              setError(t.nameHint);
              return;
            }
            create.mutate({
              name: name.trim(),
              description: description.trim() || null,
              permissions: [],
            });
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor="role-name">{t.name}</Label>
            <Input
              id="role-name"
              value={name}
              maxLength={64}
              onChange={(event) => setName(event.target.value)}
              className="h-9"
            />
            <p className="text-xs text-muted-foreground">{t.nameHint}</p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="role-description">{t.description}</Label>
            <Input
              id="role-description"
              value={description}
              maxLength={500}
              onChange={(event) => setDescription(event.target.value)}
              className="h-9"
            />
          </div>
          <FieldError message={error} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {labels.common.close}
            </Button>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending && <Loader2 className="animate-spin" aria-hidden />}
              {t.create}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
