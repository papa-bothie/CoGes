"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Bell,
  CalendarClock,
  Clock,
  KeyRound,
  LineChart,
  PackageX,
  Receipt,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { useCompanyLocale } from "@/hooks/use-me";
import { usePermission } from "@/hooks/use-permission";
import { api, unwrap } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries/keys";
import { formatDateTime } from "@/lib/format";
import { labels } from "@/lib/labels";
import { notificationHref, type AppNotification } from "@/lib/notifications";
import { cn } from "@/lib/utils";

const ICONS: Record<AppNotification["type"], { icon: LucideIcon; tone: string }> = {
  stock_low: { icon: AlertTriangle, tone: "bg-warning/10 text-warning-ink" },
  stock_out: { icon: PackageX, tone: "bg-destructive/10 text-danger-ink" },
  debt_due: { icon: Clock, tone: "bg-muted text-muted-foreground" },
  sale_cancelled: { icon: Receipt, tone: "bg-muted text-muted-foreground" },
  forecast_alert: { icon: LineChart, tone: "bg-ventes-teinte text-ventes-encre" },
  insight_critical: { icon: Sparkles, tone: "bg-destructive/10 text-danger-ink" },
  login_failures: { icon: KeyRound, tone: "bg-warning/10 text-warning-ink" },
  trial_ending: { icon: CalendarClock, tone: "bg-warning/10 text-warning-ink" },
};

/** Marque lu / non lu ; le compteur de la cloche et le tableau de bord suivent. */
export function useMarkNotification() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, read }: { id: string; read: boolean }) =>
      unwrap(
        api.PATCH("/api/v1/notifications/{notification_id}", {
          params: { path: { notification_id: id } },
          body: { read },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.notifications.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.dashboard });
    },
  });
}

/**
 * Une alerte : ouvrir le lien la marque comme lue (c'est l'avoir consultée) ; le bouton
 * de droite la bascule sans quitter la liste.
 */
export function NotificationItem({
  notification,
  onNavigate,
}: {
  notification: AppNotification;
  onNavigate?: () => void;
}) {
  const { timeZone } = useCompanyLocale();
  const canUpdate = usePermission("notifications:update");
  const mark = useMarkNotification();
  const unread = notification.read_at === null;
  const { icon: Icon, tone } = ICONS[notification.type] ?? { icon: Bell, tone: "bg-muted" };
  const t = labels.notifications;

  return (
    <li
      className={cn("flex items-start gap-3 px-3 py-3", unread && "bg-primary/5")}
      data-unread={unread || undefined}
    >
      <span className={cn("mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg", tone)}>
        <Icon className="size-4" aria-hidden />
      </span>
      <Link
        href={notificationHref(notification)}
        className="min-w-0 flex-1 rounded outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        onClick={() => {
          if (unread && canUpdate) mark.mutate({ id: notification.id, read: true });
          onNavigate?.();
        }}
      >
        <p className={cn("text-sm", unread ? "font-semibold" : "font-medium")}>
          {unread && <span className="sr-only">{t.unread} : </span>}
          {notification.title}
        </p>
        {notification.body && (
          <p className="line-clamp-2 text-sm text-muted-foreground">{notification.body}</p>
        )}
        <p className="mt-0.5 text-xs numeric text-muted-foreground">
          {formatDateTime(notification.created_at, timeZone)}
        </p>
      </Link>
      {canUpdate && (
        <Button
          variant="ghost"
          size="sm"
          className="shrink-0 text-muted-foreground"
          disabled={mark.isPending}
          onClick={() => mark.mutate({ id: notification.id, read: unread })}
        >
          {unread ? t.markRead : t.markUnread}
        </Button>
      )}
    </li>
  );
}
