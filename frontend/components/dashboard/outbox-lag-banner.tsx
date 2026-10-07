"use client";

import { useQuery } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";

import { usePermission } from "@/hooks/use-permission";
import { api, unwrap } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries/keys";
import { labels } from "@/lib/labels";

/** Au-delà, des chiffres du tableau de bord peuvent attendre le worker (ADR 0061). */
export const OUTBOX_LAG_MS = 2 * 60 * 1000;

/** Vrai si l'événement le plus ancien attend depuis plus de deux minutes. */
export function isOutboxLagging(oldestPendingAt: string | null | undefined, now: number): boolean {
  if (!oldestPendingAt) return false;
  return now - new Date(oldestPendingAt).getTime() > OUTBOX_LAG_MS;
}

/** Bandeau neutre : rien n'est à faire, sinon attendre. */
export function OutboxLagNotice() {
  return (
    <div
      role="status"
      className="flex items-center gap-3 rounded-lg border bg-muted/50 px-4 py-3 text-sm"
    >
      <RefreshCw className="size-5 shrink-0 text-muted-foreground" aria-hidden />
      <span className="min-w-0 flex-1 font-medium">{labels.dashboard.outboxLag}</span>
    </div>
  );
}

/**
 * Gérant seulement (`system:read`) : lit `GET /system/outbox` et prévient si des
 * événements attendent. Le CA du jour, lui, est déjà en direct ; ce sont les jours
 * passés, les alertes et les conseils qui prennent du retard.
 */
export function OutboxLagBanner() {
  const allowed = usePermission("system:read");
  // L'âge est figé à la réception : le rendu reste pur, la relecture le remet à jour.
  const query = useQuery({
    queryKey: queryKeys.systemOutbox,
    queryFn: async () => {
      const health = await unwrap(api.GET("/api/v1/system/outbox"));
      return isOutboxLagging(health.oldest_pending_at, Date.now());
    },
    enabled: allowed,
    refetchInterval: 60_000,
  });
  if (!allowed || !query.data) return null;
  return <OutboxLagNotice />;
}
