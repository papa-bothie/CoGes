"use client";

import { usePathname } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useMe } from "@/hooks/use-me";
import { errorMessage } from "@/lib/api/errors";
import { loginUrl, onLogoutElsewhere } from "@/lib/auth/session";
import { labels } from "@/lib/labels";

import { Header } from "./header";
import { SidebarContent } from "./sidebar";

/**
 * Coquille protégée. Au premier rendu, `GET /auth/me` déclenche le rafraîchissement
 * silencieux (le jeton d'accès n'existe qu'en mémoire) ; un refus renvoie à la connexion.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const me = useMe();
  const pathname = usePathname();

  useEffect(() => onLogoutElsewhere(() => window.location.assign(loginUrl("logout"))), []);

  if (me.isPending) return <ShellSkeleton />;

  if (me.isError) {
    return (
      <main className="grid min-h-dvh place-items-center p-6">
        <div className="max-w-md space-y-4 text-center">
          <p role="alert">{errorMessage(me.error)}</p>
          <Button onClick={() => me.refetch()}>{labels.errors.retry}</Button>
        </div>
      </main>
    );
  }

  return (
    <div className="flex min-h-dvh">
      <a
        href="#contenu"
        className="sr-only z-50 rounded-md bg-primary px-3 py-2 text-primary-foreground focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
      >
        {labels.app.skipToContent}
      </a>
      <aside className="sticky top-0 hidden h-dvh w-52 shrink-0 border-r bg-sidebar md:block">
        <SidebarContent
          companyName={me.data.company.name}
          permissions={me.data.permissions}
          pathname={pathname}
        />
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <Header me={me.data} />
        <main id="contenu" tabIndex={-1} className="flex-1 space-y-6 p-4 outline-none md:p-6">
          {children}
        </main>
      </div>
    </div>
  );
}

function ShellSkeleton() {
  return (
    <div className="flex min-h-dvh" aria-busy="true" aria-label={labels.table.loading}>
      <div className="hidden w-52 shrink-0 space-y-3 border-r p-4 md:block">
        <Skeleton className="h-9 w-32" />
        {Array.from({ length: 8 }, (_, i) => (
          <Skeleton key={i} className="h-8 w-full" />
        ))}
      </div>
      <div className="flex-1">
        <div className="flex h-16 items-center border-b bg-card px-6">
          <Skeleton className="h-5 w-40" />
        </div>
        <div className="space-y-4 p-6">
          <Skeleton className="h-8 w-56" />
          <Skeleton className="h-64 w-full" />
        </div>
      </div>
    </div>
  );
}
