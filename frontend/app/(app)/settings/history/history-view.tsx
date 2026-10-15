"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";

import { ErrorState } from "@/components/error-state";
import { PeriodPicker } from "@/components/period/period-picker";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useCompanyLocale } from "@/hooks/use-me";
import { usePeriod } from "@/hooks/use-period";
import { usePermission } from "@/hooks/use-permission";
import { useTableParams } from "@/hooks/use-table-params";
import { api, unwrap } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries/keys";
import { labels } from "@/lib/labels";
import { historyWhen } from "@/lib/settings";

const t = labels.settingsScreens.history;
const EVERYONE = "all";
const PAGE_SIZE = 30;

/**
 * Historique, maquette v2 (écran 24d) : ce qui a été fait, une phrase par geste, avec les
 * initiales de qui l'a fait. Les phrases viennent du serveur (`GET /analytics/history`,
 * ADR 0075) ; les ventes ordinaires n'y figurent pas. Filtres en haut : qui et quand.
 */
export function HistoryView() {
  const { timeZone } = useCompanyLocale();
  const table = useTableParams();
  const period = usePeriod();
  const canListUsers = usePermission("users:read");
  const actor = table.get("actor");

  const users = useQuery({
    queryKey: [...queryKeys.users.all, { page_size: 100 }],
    queryFn: () => unwrap(api.GET("/api/v1/users", { params: { query: { page_size: 100 } } })),
    enabled: canListUsers,
  });
  const filters = {
    actor_user_id: actor ?? undefined,
    from: period.fromIso ?? undefined,
    to: period.toIso ?? undefined,
  };
  const feed = useInfiniteQuery({
    queryKey: queryKeys.audit.history(filters),
    initialPageParam: 1,
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/api/v1/analytics/history", {
          params: { query: { ...filters, page: pageParam, page_size: PAGE_SIZE } },
        }),
      ),
    getNextPageParam: (last) =>
      last.page * last.page_size < last.total ? last.page + 1 : undefined,
  });
  const lines = feed.data?.pages.flatMap((page) => page.items) ?? [];

  return (
    <div className="flex flex-col gap-1.5">
      <h2 className="text-titre-carte">{t.title}</h2>
      <div className="flex flex-wrap items-center gap-2 pb-2">
        {canListUsers && (
          <Select
            value={actor ?? EVERYONE}
            onValueChange={(value) => table.setFilter("actor", value === EVERYONE ? null : value)}
          >
            <SelectTrigger aria-label={t.who} className="w-56">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={EVERYONE}>{t.everyone}</SelectItem>
              {(users.data?.items ?? []).map((user) => (
                <SelectItem key={user.id} value={user.id}>
                  {user.full_name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
        <PeriodPicker />
      </div>
      {feed.isError ? (
        <ErrorState error={feed.error} onRetry={() => void feed.refetch()} />
      ) : !feed.data ? (
        <Skeleton className="h-96 w-full rounded-champ" />
      ) : lines.length === 0 ? (
        <p className="border-t border-filet py-4 text-muted-foreground">{t.empty}</p>
      ) : (
        <ul>
          {lines.map((line) => (
            <li key={line.id} className="flex items-center gap-3 border-t border-filet py-3.5">
              <span
                aria-hidden
                className="flex size-12 shrink-0 items-center justify-center rounded-full bg-voile font-extrabold text-encre-2"
              >
                {line.initials}
              </span>
              <div className="min-w-0 flex-1">
                <div className="font-bold">{line.sentence}</div>
                <div className="text-muted-foreground">
                  <time dateTime={line.occurred_at}>{historyWhen(line.occurred_at, timeZone)}</time>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
      {feed.hasNextPage && (
        <button
          type="button"
          onClick={() => void feed.fetchNextPage()}
          disabled={feed.isFetchingNextPage}
          className="min-h-cible rounded-champ border-2 border-input bg-card font-bold outline-none hover:bg-voile focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          {t.more}
        </button>
      )}
    </div>
  );
}
