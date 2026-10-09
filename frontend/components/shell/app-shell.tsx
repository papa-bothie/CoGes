"use client";

import { usePathname } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { BottomNav, TabLink, TopBar, type BarItem } from "@/components/kit/app-bars";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useMe } from "@/hooks/use-me";
import { errorMessage } from "@/lib/api/errors";
import { loginUrl, onLogoutElsewhere } from "@/lib/auth/session";
import { labels } from "@/lib/labels";
import { ADVICE_NAV, isActive, MAIN_NAV, type NavItem } from "@/lib/navigation";
import { can, filterByPermission } from "@/lib/permissions";

import { NotificationBell } from "./notification-bell";
import { SettingsMenu } from "./settings-menu";

function barItem(item: NavItem, pathname: string): BarItem {
  return {
    href: item.href,
    label: item.label,
    icon: item.icon,
    rubrique: item.rubrique,
    active: isActive(pathname, item),
  };
}

/**
 * Coquille protégée de la maquette v2 (ADR 0070) : barre du haut à cinq entrées, Conseils,
 * cloche et engrenage ; sous 768 px, en-tête compact et barre basse fixe (écran 26).
 *
 * Au premier rendu, `GET /auth/me` déclenche le rafraîchissement silencieux (le jeton
 * d'accès n'existe qu'en mémoire) ; un refus renvoie à la connexion.
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

  // Le reçu s'affiche seul, sans barres (maquette 05) : c'est une feuille à imprimer.
  if (/\/receipt$/.test(pathname)) {
    return (
      <main
        id="contenu"
        tabIndex={-1}
        className="min-h-dvh bg-background px-4 pt-6 pb-12 outline-none md:px-marge-page print:p-0"
      >
        {children}
      </main>
    );
  }

  const items = filterByPermission(MAIN_NAV, me.data.permissions).map((item) =>
    barItem(item, pathname),
  );
  const advice = can(me.data.permissions, ADVICE_NAV.permission)
    ? barItem(ADVICE_NAV, pathname)
    : null;

  return (
    <div className="flex min-h-dvh flex-col bg-background">
      <a
        href="#contenu"
        className="sr-only z-50 rounded-md bg-primary px-3 py-2 text-primary-foreground focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
      >
        {labels.app.skipToContent}
      </a>
      <div className="contents print:hidden">
        <TopBar
          companyName={me.data.company.name}
          items={items}
          trailing={
            <>
              {advice && <TabLink item={advice} className="hidden md:flex" />}
              <NotificationBell active={pathname === "/notifications"} />
              <SettingsMenu me={me.data} />
            </>
          }
        />
      </div>
      <main
        id="contenu"
        tabIndex={-1}
        className="flex-1 space-y-6 px-4 pt-4 pb-28 outline-none md:px-marge-page md:pt-6 md:pb-12 print:p-0"
      >
        {children}
      </main>
      <div className="contents print:hidden">
        <BottomNav items={items} />
      </div>
    </div>
  );
}

function ShellSkeleton() {
  return (
    <div className="flex min-h-dvh flex-col" aria-busy="true" aria-label={labels.table.loading}>
      <div className="flex h-[72px] items-center gap-4 border-b bg-card px-marge-page">
        <Skeleton className="h-11 w-40" />
        <div className="ml-auto hidden gap-2 md:flex">
          {Array.from({ length: 5 }, (_, i) => (
            <Skeleton key={i} className="h-cible w-24" />
          ))}
        </div>
      </div>
      <div className="mx-auto w-full max-w-page space-y-4 p-6">
        <Skeleton className="h-9 w-56" />
        <Skeleton className="h-64 w-full" />
      </div>
    </div>
  );
}
