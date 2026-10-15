"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Clock, Lightbulb, Minus, User, X } from "lucide-react";
import Link from "next/link";

import { ErrorState } from "@/components/error-state";
import { useMarkNotification } from "@/components/notifications/notification-item";
import { Skeleton } from "@/components/ui/skeleton";
import { useCompanyLocale } from "@/hooks/use-me";
import { usePermission } from "@/hooks/use-permission";
import { useTableParams } from "@/hooks/use-table-params";
import { api, unwrap } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries/keys";
import { formatClock, formatDayLong } from "@/lib/format";
import { labels } from "@/lib/labels";
import {
  alertLook,
  notificationHref,
  type AlertTone,
  type AppNotification,
} from "@/lib/notifications";
import { addDays, todayIn } from "@/lib/period";
import { cn } from "@/lib/utils";

const t = labels.alerts;
const PAGE_SIZE = 50;

const TONES: Record<AlertTone, { solid: string; dot: string }> = {
  stock: { solid: "bg-stock text-primary-foreground", dot: "bg-stock" },
  depenses: { solid: "bg-depenses text-primary-foreground", dot: "bg-depenses" },
  argent: { solid: "bg-argent text-primary-foreground", dot: "bg-argent" },
  clients: { solid: "bg-clients text-primary-foreground", dot: "bg-clients" },
  neutre: { solid: "bg-foreground/80 text-background", dot: "bg-foreground/80" },
  conseils: { solid: "bg-conseils text-primary-foreground", dot: "bg-conseils" },
};

/** L'icône d'une alerte, par type (maquette 23). */
function AlertIcon({ notification }: { notification: AppNotification }) {
  const data = notification.data as Record<string, unknown>;
  const className = "size-6";
  switch (notification.type) {
    case "stock_low":
      return <AlertTriangle className={className} />;
    case "stock_out":
      return <Minus className={className} />;
    case "debt_due":
      return data.party_type === "supplier" ? (
        <Clock className={className} />
      ) : (
        <User className={className} />
      );
    case "sale_cancelled":
      return <X className={className} />;
    default:
      return <Lightbulb className={className} />;
  }
}

/** « Aujourd'hui », « Hier », sinon « Samedi 3 octobre ». */
function dayTitle(day: string, today: string): string {
  if (day === today) return t.today;
  if (day === addDays(today, -1)) return t.yesterday;
  return formatDayLong(day);
}

/**
 * Alertes, maquette v2 (écran 23) : groupées par jour, une couleur et une icône par type,
 * un point si non lue, une action directe sur chacune, « Tout marquer comme lu » et le
 * filtre « Non lues ». Le fil est personnel (ADR 0032).
 */
export function NotificationsView() {
  const { timeZone } = useCompanyLocale();
  const table = useTableParams();
  const queryClient = useQueryClient();
  const canUpdate = usePermission("notifications:update");
  const unreadOnly = table.get("unread") === "1";
  const today = todayIn(timeZone);

  const count = useQuery({
    queryKey: queryKeys.notifications.unread,
    queryFn: () => unwrap(api.GET("/api/v1/notifications/unread-count")),
  });
  const feed = useInfiniteQuery({
    queryKey: queryKeys.notifications.list({ unread: unreadOnly, infinite: true }),
    initialPageParam: 1,
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/api/v1/notifications", {
          params: {
            query: { page: pageParam, page_size: PAGE_SIZE, unread: unreadOnly || undefined },
          },
        }),
      ),
    getNextPageParam: (last) =>
      last.page * last.page_size < last.total ? last.page + 1 : undefined,
  });
  const markAll = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/notifications/read-all")),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.notifications.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.dashboard });
    },
  });

  const items = feed.data?.pages.flatMap((page) => page.items) ?? [];
  const groups: { day: string; items: AppNotification[] }[] = [];
  for (const item of items) {
    const day = todayIn(timeZone, new Date(item.created_at));
    const last = groups.at(-1);
    if (last?.day === day) last.items.push(item);
    else groups.push({ day, items: [item] });
  }
  const unread = count.data?.unread ?? 0;

  return (
    <div className="mx-auto flex max-w-[900px] flex-col gap-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-titre-page leading-[1.45] tracking-[-0.01em]">{t.title}</h1>
          <p className="text-lg text-muted-foreground">{count.data ? t.unread(unread) : "…"}</p>
        </div>
        {canUpdate && (
          <button
            type="button"
            disabled={unread === 0 || markAll.isPending}
            onClick={() => markAll.mutate()}
            className="min-h-[50px] rounded-champ border-2 border-input bg-card px-4 font-bold outline-none hover:bg-voile focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50"
          >
            {t.markAll}
          </button>
        )}
      </div>

      <div role="group" aria-label={t.filter} className="flex gap-2">
        {([false, true] as const).map((only) => (
          <button
            key={String(only)}
            type="button"
            aria-pressed={unreadOnly === only}
            onClick={() => table.setFilter("unread", only ? "1" : null)}
            className={cn(
              "min-h-12 rounded-full border-2 px-[18px] font-bold outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
              unreadOnly === only
                ? "border-foreground bg-foreground text-background"
                : "border-input bg-card hover:bg-voile",
            )}
          >
            {only ? t.unreadOnly : t.all}
          </button>
        ))}
      </div>

      {feed.isError ? (
        <ErrorState error={feed.error} onRetry={() => void feed.refetch()} />
      ) : !feed.data ? (
        <Skeleton className="h-96 w-full rounded-carte" />
      ) : items.length === 0 ? (
        <p className="rounded-carte border border-border bg-card p-carte text-lg text-muted-foreground">
          {unreadOnly ? t.emptyUnread : t.empty}
        </p>
      ) : (
        groups.map((group) => (
          <section key={group.day} className="flex flex-col gap-2.5">
            <h2 className="text-lg font-bold text-encre-2">{dayTitle(group.day, today)}</h2>
            <ul className="flex flex-col gap-2.5">
              {group.items.map((item) => (
                <AlertCard key={item.id} notification={item} timeZone={timeZone} />
              ))}
            </ul>
          </section>
        ))
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

function AlertCard({
  notification,
  timeZone,
}: {
  notification: AppNotification;
  timeZone: string;
}) {
  const canUpdate = usePermission("notifications:update");
  const mark = useMarkNotification();
  const unread = notification.read_at === null;
  const look = alertLook(notification);
  const tone = TONES[look.tone];
  return (
    <li
      data-unread={unread || undefined}
      className={cn(
        "flex gap-3.5 rounded-[20px] border border-border p-4",
        unread ? "bg-papier" : "bg-card",
      )}
    >
      <span
        aria-hidden
        className={cn(
          "flex size-[46px] shrink-0 items-center justify-center rounded-champ",
          tone.solid,
        )}
      >
        <AlertIcon notification={notification} />
      </span>
      <div className="min-w-0 flex-1 space-y-2">
        <p
          className={cn(
            "flex items-center gap-2 text-lg",
            unread ? "font-extrabold" : "font-semibold",
          )}
        >
          {unread && (
            <span className={cn("size-2.5 shrink-0 rounded-full", tone.dot)}>
              <span className="sr-only">{t.unreadDot} : </span>
            </span>
          )}
          {notification.title}
        </p>
        <p className="text-encre-2">
          {notification.body}
          {notification.body ? " · " : ""}
          <span className="numeric">{formatClock(notification.created_at, timeZone)}</span>
        </p>
        <div className="flex flex-wrap gap-2.5">
          <Link
            href={notificationHref(notification)}
            onClick={() => {
              if (unread && canUpdate) mark.mutate({ id: notification.id, read: true });
            }}
            className={cn(
              "inline-flex min-h-[50px] items-center rounded-champ px-[18px] font-bold outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
              tone.solid,
            )}
          >
            {look.action}
          </Link>
          {canUpdate && (
            <button
              type="button"
              disabled={mark.isPending}
              onClick={() => mark.mutate({ id: notification.id, read: unread })}
              className="min-h-[50px] rounded-champ border-2 border-input bg-card px-[18px] font-bold outline-none hover:bg-voile focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              {unread ? t.markRead : t.markUnread}
            </button>
          )}
        </div>
      </div>
    </li>
  );
}
