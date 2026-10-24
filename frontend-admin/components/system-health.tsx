"use client";

import Link from "next/link";
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import { api } from "@/lib/api/client";
import { errorMessage, networkError, toApiError } from "@/lib/api/errors";
import type { WorkersHealth } from "@/lib/api/schema";
import { describeProblem } from "@/lib/system";

/** Interrogation toutes les 30 s (ADR 0090) : pas de WebSocket pour ce lot. */
export const POLL_MS = 30_000;

export type HealthState =
  | { kind: "loading" }
  | { kind: "ok"; health: WorkersHealth }
  | { kind: "down"; health: WorkersHealth }
  | { kind: "unknown"; message: string };

/** `GET /platform/system/workers` (le bilan de `/system/workers`) : 200 = sain, 503 = en panne, même corps. */
export async function readWorkersHealth(): Promise<HealthState> {
  try {
    const { data, error, response } = await api.GET("/api/v1/platform/system/workers");
    if (response.status === 200 && data) return { kind: "ok", health: data };
    if (response.status === 503 && isWorkersHealth(error)) return { kind: "down", health: error };
    return { kind: "unknown", message: errorMessage(toApiError(response.status, error)) };
  } catch {
    return { kind: "unknown", message: networkError().message };
  }
}

function isWorkersHealth(value: unknown): value is WorkersHealth {
  return (
    typeof value === "object" && value !== null && Array.isArray((value as WorkersHealth).problems)
  );
}

type HealthContext = { state: HealthState; refresh: () => Promise<void> };

const Context = createContext<HealthContext>({
  state: { kind: "loading" },
  refresh: async () => undefined,
});

/** Le dernier bilan connu, partagé par le bandeau et l'écran Système. */
export function useSystemHealth(): HealthContext {
  return useContext(Context);
}

export function SystemHealthProvider({
  children,
  read = readWorkersHealth,
}: {
  children: ReactNode;
  read?: () => Promise<HealthState>;
}) {
  const [state, setState] = useState<HealthState>({ kind: "loading" });
  const refresh = useCallback(async () => setState(await read()), [read]);

  useEffect(() => {
    let alive = true;
    const poll = () => read().then((next) => alive && setState(next));
    void poll();
    const timer = window.setInterval(() => void poll(), POLL_MS);
    const onVisible = () => document.visibilityState === "visible" && void poll();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      alive = false;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [read]);

  return <Context.Provider value={{ state, refresh }}>{children}</Context.Provider>;
}

/**
 * Bandeau de panne, en haut de **toutes** les pages de l'administration : impossible
 * de manquer un système en panne en travaillant ailleurs. Chaque motif en mots, et
 * son code exact.
 */
export function SystemAlert({ state }: { state: HealthState }) {
  if (state.kind === "down") {
    return (
      <div role="alert" className="bg-danger text-surface">
        <div className="mx-auto max-w-5xl space-y-1 px-4 py-3">
          <p className="font-bold">Le système est en panne.</p>
          <ul className="space-y-0.5">
            {state.health.problems.map((code) => (
              <li key={code}>
                {describeProblem(code)}{" "}
                <code className="text-sm break-all opacity-90">({code})</code>
              </li>
            ))}
          </ul>
          <Link href="/system" className="font-semibold underline">
            Voir l&apos;état du système
          </Link>
        </div>
      </div>
    );
  }
  if (state.kind === "unknown") {
    return (
      <p className="bg-attention-teinte text-attention">
        <span className="mx-auto block max-w-5xl px-4 py-2">
          État du système inconnu : {state.message}
        </span>
      </p>
    );
  }
  return null;
}
