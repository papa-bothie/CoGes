"use client";

import { useQuery } from "@tanstack/react-query";
import { Bell } from "lucide-react";
import Link from "next/link";

import { usePermission } from "@/hooks/use-permission";
import { api, unwrap } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries/keys";
import { labels } from "@/lib/labels";
import { cn } from "@/lib/utils";

/** Compteur relu toutes les 60 s ; même clé que les mutations de lecture. */
export const UNREAD_QUERY_KEY = queryKeys.notifications.unread;

/**
 * La cloche de la maquette v2 (écrans 01 et 26) : un lien vers les alertes. Le badge
 * n'apparaît que s'il reste une alerte **grave** non lue (prompt de phase 15) ; il compte
 * alors toutes les non lues, comme la maquette. Le nom du lien les compte toujours.
 */
export function NotificationBell({ active = false }: { active?: boolean }) {
  const allowed = usePermission("notifications:read");
  const { data } = useQuery({
    queryKey: UNREAD_QUERY_KEY,
    queryFn: () => unwrap(api.GET("/api/v1/notifications/unread-count")),
    enabled: allowed,
    refetchInterval: 60_000,
  });
  if (!allowed) return null;

  const unread = data?.unread ?? 0;
  const badge = (data?.critical ?? 0) > 0 && unread > 0;
  return (
    <Link
      href="/notifications"
      aria-label={labels.shell.alerts(unread)}
      aria-current={active ? "page" : undefined}
      className={cn(
        "relative grid min-h-cible min-w-cible place-items-center rounded-touche px-3 outline-none",
        "focus-visible:ring-3 focus-visible:ring-ring/50",
        active ? "bg-voile text-foreground" : "text-encre-2 hover:bg-voile hover:text-foreground",
      )}
    >
      <Bell className="size-[22px]" aria-hidden />
      {badge && (
        <span
          aria-hidden
          className="absolute top-1 right-0.5 grid h-5 min-w-5 place-items-center rounded-full bg-stock px-1 text-mini leading-none font-extrabold numeric text-primary-foreground"
        >
          {unread > 99 ? "99+" : unread}
        </span>
      )}
    </Link>
  );
}
