"use client";

import { useQuery } from "@tanstack/react-query";
import { Bell } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { NotificationItem } from "@/components/notifications/notification-item";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { usePermission } from "@/hooks/use-permission";
import { api, unwrap } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries/keys";
import { labels } from "@/lib/labels";

/** Compteur relu toutes les 60 s ; même clé que les mutations de lecture. */
export const UNREAD_QUERY_KEY = queryKeys.notifications.unread;

const PANEL_SIZE = 15;

/** Cloche : ouvre le panneau des dernières alertes ; la page complète reste accessible. */
export function NotificationBell() {
  const allowed = usePermission("notifications:read");
  const [open, setOpen] = useState(false);
  const { data } = useQuery({
    queryKey: UNREAD_QUERY_KEY,
    queryFn: () => unwrap(api.GET("/api/v1/notifications/unread-count")),
    enabled: allowed,
    refetchInterval: 60_000,
  });
  const params = { page: 1, page_size: PANEL_SIZE };
  const list = useQuery({
    queryKey: queryKeys.notifications.list(params),
    queryFn: () => unwrap(api.GET("/api/v1/notifications", { params: { query: params } })),
    enabled: allowed && open,
  });
  if (!allowed) return null;

  const unread = data?.unread ?? 0;
  const t = labels.notifications;
  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="relative"
          aria-label={labels.header.notifications(unread)}
        >
          <Bell aria-hidden />
          {unread > 0 && (
            <span
              aria-hidden
              className="absolute -top-0.5 -right-0.5 grid h-4 min-w-4 place-items-center rounded-full bg-destructive px-1 text-2xs leading-none font-semibold numeric text-destructive-foreground"
            >
              {unread > 99 ? "99+" : unread}
            </span>
          )}
        </Button>
      </SheetTrigger>
      <SheetContent className="w-full gap-0 sm:max-w-md">
        <SheetHeader className="border-b">
          <SheetTitle>{labels.nav.notifications}</SheetTitle>
          <SheetDescription>{t.unreadCount(unread)}</SheetDescription>
        </SheetHeader>
        <div className="flex-1 overflow-y-auto">
          {list.isPending ? (
            <div className="space-y-2 p-3">
              {Array.from({ length: 5 }, (_, i) => (
                <Skeleton key={i} className="h-14 w-full" />
              ))}
            </div>
          ) : list.isError || !list.data || list.data.items.length === 0 ? (
            <p className="p-6 text-center text-sm text-muted-foreground">{t.empty}</p>
          ) : (
            <ul className="divide-y">
              {list.data.items.map((notification) => (
                <NotificationItem
                  key={notification.id}
                  notification={notification}
                  onNavigate={() => setOpen(false)}
                />
              ))}
            </ul>
          )}
        </div>
        <div className="border-t p-3 text-right">
          <Link
            href="/notifications"
            onClick={() => setOpen(false)}
            className="text-sm font-medium text-primary hover:underline"
          >
            {t.seeAll}
          </Link>
        </div>
      </SheetContent>
    </Sheet>
  );
}
