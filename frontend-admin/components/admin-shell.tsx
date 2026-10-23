"use client";

import Link from "next/link";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { SystemAlert, SystemHealthProvider, useSystemHealth } from "@/components/system-health";
import { api, unwrap } from "@/lib/api/client";
import type { PlatformMe } from "@/lib/api/schema";
import { loginUrl, logout, onLogoutElsewhere } from "@/lib/auth/session";

const ROLE_NAMES: Record<string, string> = {
  administrator: "Administrateur",
  support: "Support",
};

const MeContext = createContext<PlatformMe | null>(null);

/** Le profil connecté, pour masquer ce qu'il ne peut pas faire (le serveur revérifie). */
export function useMe(): PlatformMe | null {
  return useContext(MeContext);
}

export function AdminShell({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<PlatformMe | null>(null);

  useEffect(() => {
    unwrap(api.GET("/api/v1/platform/auth/me")).then(setMe, () => undefined);
    return onLogoutElsewhere(() => window.location.assign(loginUrl()));
  }, []);

  async function signOut() {
    await logout();
    window.location.assign(loginUrl());
  }

  return (
    <SystemHealthProvider>
      <div className="min-h-screen">
        <HealthBanner />
        <header className="border-b border-trait bg-surface">
          <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
            <Link href="/companies" className="font-bold">
              CoGes — Administration
            </Link>
            <nav aria-label="Navigation principale" className="flex flex-1 gap-4">
              <Link href="/companies" className="text-encre-douce hover:text-encre">
                Entreprises
              </Link>
              <Link href="/system" className="text-encre-douce hover:text-encre">
                Système
              </Link>
              <Link href="/system/jobs" className="text-encre-douce hover:text-encre">
                Tâches
              </Link>
            </nav>
            {me && (
              <span className="text-sm text-encre-douce">
                {me.display_name} · {ROLE_NAMES[me.role] ?? me.role}
              </span>
            )}
            <button
              type="button"
              onClick={signOut}
              className="rounded border border-trait px-3 py-1.5 text-sm font-semibold"
            >
              Se déconnecter
            </button>
          </div>
        </header>
        <main className="mx-auto max-w-5xl px-4 py-6">
          <MeContext.Provider value={me}>{children}</MeContext.Provider>
        </main>
      </div>
    </SystemHealthProvider>
  );
}

function HealthBanner() {
  return <SystemAlert state={useSystemHealth().state} />;
}
