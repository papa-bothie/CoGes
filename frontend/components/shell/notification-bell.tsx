"use client";

import { useQuery } from "@tanstack/react-query";
import { Bell } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { usePermission } from "@/hooks/use-permission";
import { api, unwrap } from "@/lib/api/client";
import { labels } from "@/lib/labels";

export const UNREAD_QUERY_KEY = ["notifications", "unread-count"] as const;

/** Cloche reliée à `/notifications`, compteur relu toutes les 60 s. */
export function NotificationBell() {
  const allowed = usePermission("notifications:read");
  const { data } = useQuery({
    queryKey: UNREAD_QUERY_KEY,
    queryFn: () => unwrap(api.GET("/api/v1/notifications/unread-count")),
    enabled: allowed,
    refetchInterval: 60_000,
  });
  if (!allowed) return null;

  const unread = data?.unread ?? 0;
  return (
    <Button variant="ghost" size="icon" asChild className="relative">
      <Link href="/notifications" aria-label={labels.header.notifications(unread)}>
        <Bell aria-hidden />
        {unread > 0 && (
          <span
            aria-hidden
            className="absolute -top-0.5 -right-0.5 grid h-4 min-w-4 place-items-center rounded-full bg-destructive px-1 text-[10px] leading-none font-semibold numeric text-destructive-foreground"
          >
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </Link>
    </Button>
  );
}
