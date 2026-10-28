"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Minus } from "lucide-react";
import { toast } from "sonner";

import { ErrorState } from "@/components/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { ME_QUERY_KEY } from "@/hooks/use-me";
import { usePermission } from "@/hooks/use-permission";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { labels } from "@/lib/labels";
import { toggleAbility } from "@/lib/settings";
import { cn } from "@/lib/utils";

type Grid = Schemas["AbilityGrid"];
type RoleAbilities = Schemas["RoleAbilities"];
type Ability = Schemas["AbilityRead"];
const t = labels.settingsScreens.rights;

/**
 * Qui peut faire quoi, maquette v2 (écran 24c) : quatorze gestes, trois rôles (ADR 0099).
 * Une case cochée donne au rôle tous les droits de la ligne, décochée elle les retire. Une
 * ligne « en partie » (réglée avant la grille regroupée) garde ses droits tant qu'on n'y
 * touche pas : un appui la complète, un second la retire. Le gérant garde tout ; l'accueil
 * et les alertes, les personnes et les réglages ne se changent pas ici.
 */
export function RightsView() {
  const queryClient = useQueryClient();
  const canEdit = usePermission("roles:update");
  const query = useQuery({
    queryKey: queryKeys.roles.abilities,
    queryFn: () => unwrap(api.GET("/api/v1/roles/abilities")),
  });
  const save = useMutation({
    meta: { toastError: false },
    mutationFn: ({ role, abilities }: { role: RoleAbilities; abilities: string[] }) =>
      unwrap(
        api.PUT("/api/v1/roles/{role_id}/abilities", {
          params: { path: { role_id: role.role_id } },
          body: { abilities },
        }),
      ),
    onMutate: async ({ role, abilities }) => {
      // La case change tout de suite ; un refus du serveur la remet en place.
      await queryClient.cancelQueries({ queryKey: queryKeys.roles.abilities });
      const previous = queryClient.getQueryData<Grid>(queryKeys.roles.abilities);
      queryClient.setQueryData<Grid>(
        queryKeys.roles.abilities,
        (grid) =>
          grid && {
            ...grid,
            roles: grid.roles.map((item) =>
              item.role_id === role.role_id ? { ...item, abilities } : item,
            ),
          },
      );
      return { previous };
    },
    onError: (error, _variables, context) => {
      if (context?.previous) queryClient.setQueryData(queryKeys.roles.abilities, context.previous);
      toast.error(errorMessage(error));
    },
    onSuccess: () => toast.success(t.saved),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.roles.abilities });
      void queryClient.invalidateQueries({ queryKey: queryKeys.roles.all });
      void queryClient.invalidateQueries({ queryKey: ME_QUERY_KEY });
    },
  });

  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  const grid = query.data;
  const order = grid?.abilities.map((item) => item.key) ?? [];
  const cellProps = {
    canEdit,
    pending: save.isPending,
    onToggle: (role: RoleAbilities, key: string) =>
      save.mutate({ role, abilities: toggleAbility(order, role.abilities, key) }),
  };

  return (
    <div className="flex flex-col gap-2">
      <h2 className="text-titre-carte">{t.title}</h2>
      {grid?.roles.some((role) => role.partial.length > 0) && (
        <p className="rounded-champ bg-voile px-4 py-3 font-semibold">{t.partialHint}</p>
      )}
      {!grid ? (
        <Skeleton className="h-[540px] w-full rounded-champ" />
      ) : (
        <>
          {/* Sous 640 px : une carte par rôle, sans défilement horizontal. */}
          <div className="flex flex-col gap-3 sm:hidden">
            {grid.roles.map((role) => (
              <section key={role.role_id} className="rounded-tuile border border-border">
                <h3 className="border-b-2 border-border px-4 py-3 font-extrabold">{role.label}</h3>
                <ul>
                  {grid.abilities.map((line) => (
                    <li
                      key={line.key}
                      className="flex items-center justify-between gap-3 border-b border-filet px-4 py-2 last:border-b-0"
                    >
                      <span className="font-semibold">
                        {line.label}
                        {line.locked && <span className="sr-only"> ({t.locked})</span>}
                      </span>
                      <Cell line={line} role={role} {...cellProps} />
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </div>
          <div className="hidden sm:block">
            <table className="w-full border-collapse">
              <colgroup>
                <col style={{ width: "50%" }} />
                {grid.roles.map((role) => (
                  <col key={role.role_id} />
                ))}
              </colgroup>
              <thead>
                <tr className="border-b-2 border-border">
                  <th scope="col" className="py-2.5 text-left font-extrabold">
                    {t.action}
                  </th>
                  {grid.roles.map((role) => (
                    <th
                      key={role.role_id}
                      scope="col"
                      className="py-2.5 text-center font-extrabold"
                    >
                      {role.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {grid.abilities.map((line) => (
                  <tr key={line.key} className="border-b border-filet">
                    <th scope="row" className="py-2 text-left font-semibold">
                      {line.label}
                      {line.locked && <span className="sr-only"> ({t.locked})</span>}
                    </th>
                    {grid.roles.map((role) => (
                      <td key={role.role_id} className="py-2">
                        <Cell line={line} role={role} {...cellProps} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

/**
 * Une case de la grille : cochée en vert plein, adoucie et verrouillée pour le gérant ;
 * « en partie » avec un trait et le mot écrit (jamais la couleur seule, ADR 0099).
 */
function Cell({
  line,
  role,
  canEdit,
  pending,
  onToggle,
}: {
  line: Ability;
  role: RoleAbilities;
  canEdit: boolean;
  pending: boolean;
  onToggle: (role: RoleAbilities, key: string) => void;
}) {
  const on = role.abilities.includes(line.key);
  const partial = !on && role.partial.includes(line.key);
  const locked = role.locked || line.locked || !canEdit;
  return (
    <span className="flex items-center gap-2 sm:flex-col sm:gap-0.5">
      <button
        type="button"
        aria-pressed={partial ? "mixed" : on}
        aria-label={
          partial ? t.partialAria(line.label, role.label) : t.aria(line.label, role.label)
        }
        disabled={locked || pending}
        onClick={() => onToggle(role, line.key)}
        className={cn(
          "flex size-12 shrink-0 items-center justify-center rounded-touche border-2 text-primary-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50 sm:mx-auto",
          on
            ? role.locked
              ? "border-primary/65 bg-primary/65"
              : "border-primary bg-primary"
            : partial
              ? "border-primary bg-card text-primary"
              : "border-input bg-card",
          locked ? "cursor-not-allowed" : "cursor-pointer hover:brightness-95",
        )}
      >
        {partial ? (
          <Minus aria-hidden className="size-[22px]" />
        ) : (
          <Check aria-hidden className={cn("size-[22px]", !on && "opacity-0")} />
        )}
      </button>
      {partial && (
        <span aria-hidden className="text-sm font-semibold text-muted-foreground">
          {t.partial}
        </span>
      )}
    </span>
  );
}
