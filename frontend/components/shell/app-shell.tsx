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
import { NoAccess } from "@/components/shell/no-access";
import { routeRule } from "@/lib/access";
import { can } from "@/lib/permissions";
import {
  ADVICE_NAV,
  isActive,
  MAIN_NAV,
  resolveNav,
  type ResolvedNavItem,
  visibleNav,
} from "@/lib/navigation";

import { InstallInvite } from "@/components/pwa/install-invite";

import { ConnectionBanner } from "./connection-banner";
import { NotificationBell } from "./notification-bell";
import { SettingsMenu } from "./settings-menu";
import { SupportBanner } from "./support-banner";
import { purgeExpiredDrafts, setDraftOwner } from "@/lib/drafts";
import { isSupportMode } from "@/lib/auth/support";

function barItem(item: ResolvedNavItem, pathname: string): BarItem {
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
  // Brouillons (ADR 0101) : rangés au nom de cette personne dans cette entreprise, et
  // tout ce qui a plus de 24 heures disparaît à l'ouverture.
  const companyId = me.data?.company.id;
  const userId = me.data?.user.id;
  useEffect(() => {
    purgeExpiredDrafts();
    if (companyId && userId && !isSupportMode()) setDraftOwner({ companyId, userId });
  }, [companyId, userId]);
  const mustChange = me.data?.user.must_change_password === true;
  // Mot de passe provisoire (ADR 0074) : rien d'autre ne répond tant qu'il n'est pas changé.
  useEffect(() => {
    if (mustChange) window.location.replace("/password");
  }, [mustChange]);

  if (me.isPending || mustChange) return <ShellSkeleton />;

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

  // Garde de page (ADR 0099) : le droit exact du registre, sinon la page n'est pas rendue.
  const rule = routeRule(pathname);
  const allowed = rule === undefined || rule === null || can(me.data.permissions, rule);
  const page = allowed ? (
    children
  ) : (
    <NoAccess home={resolveNav(MAIN_NAV[0]!, me.data.permissions)?.href ?? null} />
  );

  // Le reçu s'affiche seul, sans barres (maquette 05) : c'est une feuille à imprimer.
  if (/\/receipt$/.test(pathname)) {
    return (
      <main
        id="contenu"
        tabIndex={-1}
        className="min-h-dvh bg-background px-4 pt-6 pb-12 outline-none md:px-marge-page print:p-0"
      >
        {page}
      </main>
    );
  }

  const items = visibleNav(MAIN_NAV, me.data.permissions).map((item) => barItem(item, pathname));
  const adviceItem = resolveNav(ADVICE_NAV, me.data.permissions);
  const advice = adviceItem ? barItem(adviceItem, pathname) : null;

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
        <SupportBanner />
        <ConnectionBanner />
        <InstallInvite />
        {page}
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
