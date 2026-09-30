"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { FieldError } from "@/components/field-error";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage, isApiError } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { labels } from "@/lib/labels";

type Role = Schemas["RoleRead"];
type User = Schemas["UserRead"];

function RoleChoices({
  roles,
  selected,
  onChange,
}: {
  roles: readonly Role[];
  selected: ReadonlySet<string>;
  onChange: (next: Set<string>) => void;
}) {
  return (
    <fieldset className="space-y-2">
      <legend className="mb-1 text-sm font-medium">{labels.settings.users.roles}</legend>
      {roles.map((role) => (
        <label key={role.id} className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            className="size-4 accent-primary"
            checked={selected.has(role.id)}
            onChange={(event) => {
              const next = new Set(selected);
              if (event.target.checked) next.add(role.id);
              else next.delete(role.id);
              onChange(next);
            }}
          />
          {role.description ?? role.name}
        </label>
      ))}
    </fieldset>
  );
}

/** Création d'un compte (`POST /users`), rôles attribués dans la même requête. */
export function CreateUserDialog({
  open,
  onOpenChange,
  roles,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  roles: readonly Role[];
}) {
  const queryClient = useQueryClient();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [errors, setErrors] = useState<
    Partial<Record<"fullName" | "email" | "password" | "roles" | "form", string>>
  >({});
  const t = labels.settings.users;

  const reset = () => {
    setFullName("");
    setEmail("");
    setPassword("");
    setSelected(new Set());
    setErrors({});
  };

  const create = useMutation({
    meta: { toastError: false },
    mutationFn: (body: Schemas["UserCreate"]) => unwrap(api.POST("/api/v1/users", { body })),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.users.all });
      toast.success(t.created);
      reset();
      onOpenChange(false);
    },
    onError: (error) => {
      const fields = isApiError(error) ? error.fieldErrors() : {};
      setErrors(fields.email ? { email: labels.validation.email } : { form: errorMessage(error) });
    },
  });

  const submit = () => {
    const next: typeof errors = {};
    if (!fullName.trim()) next.fullName = labels.validation.required;
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) next.email = labels.validation.email;
    if (password.length < 12) next.password = t.passwordTooShort;
    if (selected.size === 0) next.roles = t.noRole;
    setErrors(next);
    if (Object.keys(next).length > 0) return;
    create.mutate({
      full_name: fullName.trim(),
      email: email.trim(),
      password,
      role_ids: [...selected],
    });
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) reset();
        onOpenChange(next);
      }}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t.createTitle}</DialogTitle>
        </DialogHeader>
        <form
          className="space-y-4"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor="user-name">{t.fullName}</Label>
            <Input
              id="user-name"
              value={fullName}
              maxLength={200}
              onChange={(event) => setFullName(event.target.value)}
              className="h-9"
            />
            <FieldError message={errors.fullName} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="user-email">{t.email}</Label>
            <Input
              id="user-email"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              className="h-9"
            />
            <FieldError message={errors.email} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="user-password">{t.password}</Label>
            <Input
              id="user-password"
              type="password"
              autoComplete="new-password"
              value={password}
              maxLength={128}
              onChange={(event) => setPassword(event.target.value)}
              className="h-9"
            />
            <p className="text-xs text-muted-foreground">{t.passwordHint}</p>
            <FieldError message={errors.password} />
          </div>
          <RoleChoices roles={roles} selected={selected} onChange={setSelected} />
          <FieldError message={errors.roles} />
          <FieldError message={errors.form} />
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

/**
 * Rôles d'un compte : les différences sont envoyées une à une (attribution, puis retrait).
 * Un retrait refusé — dernier gérant actif (409 `last_manager`, ADR 0054) — s'affiche ici.
 */
export function UserRolesDialog({
  user,
  roles,
  onClose,
}: {
  user: User;
  roles: readonly Role[];
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const initial = new Set((user.roles ?? []).map((role) => role.id));
  const [selected, setSelected] = useState<Set<string>>(initial);
  const [error, setError] = useState<string | null>(null);
  const t = labels.settings.users;

  const save = useMutation({
    meta: { toastError: false },
    mutationFn: async () => {
      for (const role of roles) {
        const path = { user_id: user.id, role_id: role.id };
        if (selected.has(role.id) && !initial.has(role.id)) {
          await unwrap(
            api.POST("/api/v1/users/{user_id}/roles", {
              params: { path: { user_id: user.id } },
              body: { role_id: role.id },
            }),
          );
        } else if (!selected.has(role.id) && initial.has(role.id)) {
          await unwrap(api.DELETE("/api/v1/users/{user_id}/roles/{role_id}", { params: { path } }));
        }
      }
    },
    onSettled: () => void queryClient.invalidateQueries({ queryKey: queryKeys.users.all }),
    onSuccess: () => {
      toast.success(t.rolesSaved);
      onClose();
    },
    onError: (caught) => setError(errorMessage(caught)),
  });

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>{t.rolesTitle(user.full_name)}</DialogTitle>
        </DialogHeader>
        <RoleChoices roles={roles} selected={selected} onChange={setSelected} />
        <FieldError message={error} />
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            {labels.common.close}
          </Button>
          <Button
            type="button"
            disabled={save.isPending || selected.size === 0}
            onClick={() => {
              setError(null);
              save.mutate();
            }}
          >
            {save.isPending && <Loader2 className="animate-spin" aria-hidden />}
            {labels.common.save}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
