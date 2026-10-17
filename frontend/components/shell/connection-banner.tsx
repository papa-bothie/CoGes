"use client";

import { type Query, useQueryClient } from "@tanstack/react-query";
import { WifiOff } from "lucide-react";
import { useCallback, useSyncExternalStore } from "react";

import { Button } from "@/components/ui/button";
import { isTransient } from "@/lib/api/errors";
import { labels } from "@/lib/labels";

const t = labels.incident;

export type ConnectionState = "ok" | "retrying" | "lost";

/**
 * État de la connexion d'après les LECTURES en cours (ADR 0085) : une coupure réseau ou
 * une API arrêtée (502, 503, 504) que TanStack Query réessaie (2, 4, 8 s), puis abandonne.
 * Les écritures n'entrent pas en compte : elles ne sont jamais rejouées en silence.
 */
export function connectionState(queries: readonly Query[]): ConnectionState {
  let lost = false;
  for (const query of queries) {
    const { fetchStatus, fetchFailureReason, status, error } = query.state;
    if (fetchStatus === "fetching" && isTransient(fetchFailureReason)) return "retrying";
    if (status === "error" && fetchStatus === "idle" && isTransient(error)) lost = true;
  }
  return lost ? "lost" : "ok";
}

/** Bandeau discret en haut du contenu ; rien quand tout va bien. */
export function ConnectionBanner() {
  const client = useQueryClient();
  const cache = client.getQueryCache();
  const subscribe = useCallback((notify: () => void) => cache.subscribe(notify), [cache]);
  const state = useSyncExternalStore(
    subscribe,
    () => connectionState(cache.getAll()),
    () => "ok" as const,
  );
  if (state === "ok") return null;

  const retryNow = () =>
    void client.refetchQueries({
      predicate: (query) => query.state.status === "error" && isTransient(query.state.error),
    });

  return (
    <div
      role="status"
      className="flex items-center gap-3 rounded-lg border border-warning/30 bg-warning/5 px-4 py-3 text-sm text-warning-ink"
    >
      <WifiOff className="size-5 shrink-0" aria-hidden />
      <span className="min-w-0 flex-1 font-medium">
        {state === "retrying" ? t.connectionRetrying : t.connectionLost}
      </span>
      {state === "lost" && (
        <Button size="sm" variant="outline" onClick={retryNow}>
          {t.retry}
        </Button>
      )}
    </div>
  );
}
