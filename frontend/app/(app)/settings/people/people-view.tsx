"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useId, useState } from "react";
import { toast } from "sonner";

import { ErrorState } from "@/components/error-state";
import { FieldError } from "@/components/field-error";
import { Chip } from "@/components/kit/chip";
import { initials } from "@/components/kit/list-row";
import { fieldClasses } from "@/components/kit/rubrique";
import { Skeleton } from "@/components/ui/skeleton";
import { useCompanyLocale, useMe } from "@/hooks/use-me";
import { usePermission } from "@/hooks/use-permission";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { formatDayMonth } from "@/lib/format";
import { labels } from "@/lib/labels";
import { contactOf, seenWhen, temporaryDeadline } from "@/lib/settings";
import { cn } from "@/lib/utils";

type User = Schemas["UserRead"];
type Role = Schemas["RoleRead"];
const t = labels.settingsScreens.people;

/** Les trois rôles de la grille, dans cet ordre ; les rôles sur mesure restent dans l'API. */
const GRID_ROLES = ["gerant", "vendeur", "comptable"] as const;

function useSystemRoles() {
  return useQuery({
    queryKey: queryKeys.roles.all,
    queryFn: () => unwrap(api.GET("/api/v1/roles", { params: { query: { page_size: 100 } } })),
    select: (page) =>
      GRID_ROLES.map((name) =>
        page.items.find((role) => role.is_system && role.name === name),
      ).filter((role): role is Role => Boolean(role)),
  });
}

const roleLabel = (role: Pick<Role, "name" | "description">) => role.description ?? role.name;

/**
 * Personnes, maquette v2 (écran 24b) : qui utilise CoGes, quand on l'a vu, et l'accès qu'on
 * coupe ou redonne. On ajoute une personne ici même ; son mot de passe provisoire s'affiche
 * une seule fois (ADR 0074). Le dernier gérant actif reste toujours (ADR 0054).
 */
export function PeopleView() {
  const { data: me } = useMe();
  const { timeZone } = useCompanyLocale();
  const queryClient = useQueryClient();
  const canCreate = usePermission("users:create");
  const canUpdate = usePermission("users:update");
  const canEditRoles = usePermission("roles:update");
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  // Provisoire tiré par « Donner un nouveau mot de passe » : affiché une seule fois.
  const [drawn, setDrawn] = useState<{ id: string; name: string; password: string } | null>(null);
  const roles = useSystemRoles();
  const users = useQuery({
    queryKey: [...queryKeys.users.all, { page_size: 100 }],
    queryFn: () => unwrap(api.GET("/api/v1/users", { params: { query: { page_size: 100 } } })),
  });

  const toggle = useMutation({
    meta: { toastError: false },
    mutationFn: (user: User) =>
      unwrap(
        api.PATCH("/api/v1/users/{user_id}", {
          params: { path: { user_id: user.id } },
          body: { is_active: !user.is_active },
        }),
      ),
    onSuccess: (user) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.users.all });
      toast.success(user.is_active ? t.backDone(user.full_name) : t.cutDone(user.full_name));
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const redraw = useMutation({
    meta: { toastError: false },
    mutationFn: (user: User) =>
      unwrap(
        api.POST("/api/v1/users/{user_id}/password", {
          params: { path: { user_id: user.id } },
          body: {},
        }),
      ),
    onSuccess: (user) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.users.all });
      if (user.temporary_password) {
        setDrawn({ id: user.id, name: user.full_name, password: user.temporary_password });
      }
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  if (users.isError) return <ErrorState error={users.error} onRetry={() => void users.refetch()} />;

  // Actifs d'abord (dans l'ordre de l'API), puis les accès coupés.
  const people = [...(users.data?.items ?? [])].sort(
    (a, b) => Number(b.is_active) - Number(a.is_active),
  );

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-titre-carte">{t.title}</h2>
        {canCreate && (
          <button
            type="button"
            aria-expanded={adding}
            onClick={() => setAdding((open) => !open)}
            className="inline-flex min-h-[54px] items-center rounded-champ bg-primary px-5 font-bold text-primary-foreground outline-none hover:bg-primary/90 focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            {adding ? t.close : t.add}
          </button>
        )}
      </div>
      {adding && <AddPerson roles={roles.data ?? []} />}
      {!users.data ? (
        <Skeleton className="mt-3 h-64 w-full rounded-champ" />
      ) : (
        <ul>
          {people.map((user) => {
            const you = user.id === me?.user.id;
            const role = user.roles?.[0];
            const last = !user.is_active
              ? user.deactivated_at
                ? t.cutOn(formatDayMonth(user.deactivated_at, timeZone))
                : t.cutOn("—")
              : you
                ? t.online
                : user.last_login_at
                  ? t.seen(seenWhen(user.last_login_at, timeZone))
                  : t.never;
            return (
              <li
                key={user.id}
                className="flex flex-wrap items-center gap-3 border-t border-filet py-3.5"
              >
                <span
                  aria-hidden
                  className={cn(
                    "flex size-12 shrink-0 items-center justify-center rounded-full font-extrabold",
                    user.is_active ? "bg-ventes-teinte text-ventes-encre" : "bg-voile text-encre-2",
                  )}
                >
                  {initials(user.full_name)}
                </span>
                <div
                  className={cn(
                    "min-w-0 flex-[1_1_200px]",
                    !user.is_active && "text-muted-foreground",
                  )}
                >
                  <div className="text-[17px] font-bold">{user.full_name}</div>
                  <div className="text-muted-foreground">
                    {role ? roleLabel(role) : "—"} · {last}
                  </div>
                  {user.is_active && !you && user.must_change_password && (
                    <TemporaryLine
                      user={user}
                      timeZone={timeZone}
                      canRedraw={canUpdate}
                      pending={redraw.isPending}
                      onRedraw={() => redraw.mutate(user)}
                    />
                  )}
                  {user.is_active && !you && !user.must_change_password && canUpdate && (
                    <button
                      type="button"
                      disabled={redraw.isPending}
                      onClick={() => redraw.mutate(user)}
                      className="mt-1 mr-4 text-sm font-semibold text-primary underline-offset-4 outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50"
                    >
                      {t.newPassword}
                    </button>
                  )}
                  {canEditRoles && !you && user.is_active && (
                    <button
                      type="button"
                      aria-expanded={editing === user.id}
                      onClick={() => setEditing(editing === user.id ? null : user.id)}
                      className="mt-1 text-sm font-semibold text-primary underline-offset-4 outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50"
                    >
                      {t.changeRole}
                    </button>
                  )}
                </div>
                {you ? (
                  <button
                    type="button"
                    disabled
                    className="min-h-[54px] rounded-champ border-2 border-input bg-card px-5 font-bold"
                  >
                    {t.you}
                  </button>
                ) : (
                  canUpdate && (
                    <button
                      type="button"
                      disabled={toggle.isPending}
                      onClick={() => toggle.mutate(user)}
                      className={cn(
                        "min-h-[54px] rounded-champ border-2 border-input bg-card px-5 font-bold outline-none hover:bg-voile focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50",
                        !user.is_active && "text-muted-foreground",
                      )}
                    >
                      {user.is_active ? t.cut : t.giveBack}
                    </button>
                  )
                )}
                {drawn?.id === user.id && (
                  <p
                    role="status"
                    className="basis-full rounded-champ bg-card px-3.5 py-3 font-semibold"
                  >
                    {t.newPasswordFor(drawn.name)}{" "}
                    <span className="font-extrabold tracking-[0.06em] numeric">
                      {drawn.password}
                    </span>{" "}
                    {t.newPasswordHint}
                  </p>
                )}
                {editing === user.id && (
                  <RoleEditor
                    user={user}
                    roles={roles.data ?? []}
                    onDone={() => setEditing(null)}
                  />
                )}
              </li>
            );
          })}
        </ul>
      )}
      <p className="mt-1.5 text-muted-foreground">{t.lastManager}</p>
    </div>
  );
}

/** « Mot de passe provisoire · Expire le 19/10 à 14 h 05 » (ou « Expiré »), et le geste pour en redonner un. */
function TemporaryLine({
  user,
  timeZone,
  canRedraw,
  pending,
  onRedraw,
}: {
  user: User;
  timeZone: string;
  canRedraw: boolean;
  pending: boolean;
  onRedraw: () => void;
}) {
  const until = user.must_change_password_until;
  const deadline = until ? temporaryDeadline(until, timeZone) : null;
  const expired = deadline === t.expired;
  return (
    <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
      <span className={cn("font-semibold", expired ? "text-depenses-encre" : "text-encre-2")}>
        {t.temporaryLabel}
        {deadline && ` · ${deadline}`}
      </span>
      {canRedraw && (
        <button
          type="button"
          disabled={pending}
          onClick={onRedraw}
          className="font-semibold text-primary underline-offset-4 outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50"
        >
          {t.newPassword}
        </button>
      )}
    </div>
  );
}

function RoleChips({
  roles,
  value,
  onChange,
  labelledBy,
}: {
  roles: readonly Role[];
  value: string | null;
  onChange: (id: string) => void;
  labelledBy: string;
}) {
  return (
    <div role="group" aria-labelledby={labelledBy} className="flex flex-wrap gap-2">
      {roles.map((role) => (
        <Chip
          key={role.id}
          selected={value === role.id}
          className="text-[15px]"
          onClick={() => onChange(role.id)}
        >
          {roleLabel(role)}
        </Chip>
      ))}
    </div>
  );
}

/** « + Ajouter une personne » : nom, téléphone ou e-mail, rôle ; le serveur tire le mot de passe. */
function AddPerson({ roles }: { roles: readonly Role[] }) {
  const queryClient = useQueryClient();
  const id = useId();
  const [name, setName] = useState("");
  const [contact, setContact] = useState("");
  const [roleId, setRoleId] = useState<string | null>(null);
  const [errors, setErrors] = useState<{ name?: string; contact?: string; form?: string }>({});
  const [created, setCreated] = useState<Schemas["UserCreated"] | null>(null);
  const chosen = roleId ?? roles.find((role) => role.name === "vendeur")?.id ?? null;

  const create = useMutation({
    meta: { toastError: false },
    mutationFn: (body: Schemas["UserCreate"]) => unwrap(api.POST("/api/v1/users", { body })),
    onSuccess: (user) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.users.all });
      setCreated(user);
      setName("");
      setContact("");
      toast.success(t.created(user.full_name));
    },
    onError: (error) => setErrors({ form: errorMessage(error) }),
  });

  const submit = () => {
    const parsed = contactOf(contact);
    const next: typeof errors = {};
    if (!name.trim()) next.name = t.required;
    if (!parsed) next.contact = t.invalidContact;
    setErrors(next);
    if (!parsed || next.name) return;
    create.mutate({ full_name: name.trim(), ...parsed, role_ids: chosen ? [chosen] : [] });
  };

  const input = cn(fieldClasses("ventes"), "min-h-[54px] px-3.5 text-[17px]");
  return (
    <form
      noValidate
      className="mt-2.5 flex flex-col gap-3 rounded-tuile bg-papier p-4"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <div className="grid grid-cols-[repeat(auto-fit,minmax(220px,1fr))] gap-3">
        <div>
          <label htmlFor={`${id}-name`} className="mb-1.5 block font-bold">
            {t.name}
          </label>
          <input
            id={`${id}-name`}
            className={input}
            placeholder={t.namePlaceholder}
            value={name}
            maxLength={200}
            aria-invalid={Boolean(errors.name)}
            onChange={(event) => setName(event.target.value)}
          />
          <FieldError message={errors.name} />
        </div>
        <div>
          <label htmlFor={`${id}-contact`} className="mb-1.5 block font-bold">
            {t.contact}
          </label>
          <input
            id={`${id}-contact`}
            className={input}
            placeholder={t.contactPlaceholder}
            value={contact}
            autoComplete="off"
            aria-invalid={Boolean(errors.contact)}
            onChange={(event) => setContact(event.target.value)}
          />
          <FieldError message={errors.contact} />
        </div>
      </div>
      <span id={`${id}-role`} className="font-bold">
        {t.role}
      </span>
      <RoleChips roles={roles} value={chosen} onChange={setRoleId} labelledBy={`${id}-role`} />
      {created?.temporary_password && (
        <p role="status" className="rounded-champ bg-card px-3.5 py-3 font-semibold">
          {t.temporary}{" "}
          <span className="font-extrabold tracking-[0.06em] numeric">
            {created.temporary_password}
          </span>{" "}
          {t.temporaryHint}
        </p>
      )}
      <FieldError message={errors.form} />
      <button
        type="submit"
        disabled={create.isPending}
        className="inline-flex min-h-[54px] items-center gap-2 self-start rounded-champ bg-primary px-5 font-bold text-primary-foreground outline-none hover:bg-primary/90 focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50"
      >
        {create.isPending && <Loader2 className="size-4 animate-spin" aria-hidden />}
        {t.create}
      </button>
    </form>
  );
}

/** « Changer son rôle » : un seul rôle de la grille ; l'ancien est retiré après le nouveau. */
function RoleEditor({
  user,
  roles,
  onDone,
}: {
  user: User;
  roles: readonly Role[];
  onDone: () => void;
}) {
  const queryClient = useQueryClient();
  const id = useId();
  const current = (user.roles ?? []).find((role) => roles.some((item) => item.id === role.id));
  const [roleId, setRoleId] = useState<string | null>(current?.id ?? null);
  const save = useMutation({
    meta: { toastError: false },
    mutationFn: async (next: string) => {
      await unwrap(
        api.POST("/api/v1/users/{user_id}/roles", {
          params: { path: { user_id: user.id } },
          body: { role_id: next },
        }),
      );
      for (const role of user.roles ?? []) {
        if (role.id === next || !roles.some((item) => item.id === role.id)) continue;
        await unwrap(
          api.DELETE("/api/v1/users/{user_id}/roles/{role_id}", {
            params: { path: { user_id: user.id, role_id: role.id } },
          }),
        );
      }
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.users.all });
      toast.success(t.roleSaved);
      onDone();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
  return (
    <div className="flex w-full flex-col gap-2.5 rounded-tuile bg-papier p-4">
      <span id={`${id}-role`} className="font-bold">
        {t.role}
      </span>
      <RoleChips roles={roles} value={roleId} onChange={setRoleId} labelledBy={`${id}-role`} />
      <button
        type="button"
        disabled={!roleId || roleId === current?.id || save.isPending}
        onClick={() => roleId && save.mutate(roleId)}
        className="inline-flex min-h-cible items-center gap-2 self-start rounded-champ bg-primary px-5 font-bold text-primary-foreground outline-none hover:bg-primary/90 focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50"
      >
        {save.isPending && <Loader2 className="size-4 animate-spin" aria-hidden />}
        {t.saveRole}
      </button>
    </div>
  );
}
