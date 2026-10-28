"use client";

import { LogOut, Menu, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";

import { GlobalSearch } from "@/components/global-search";
import { ThemeToggle } from "@/components/theme-toggle";
import { SystemAlert, SystemHealthProvider, useSystemHealth } from "@/components/system-health";
import { api, unwrap } from "@/lib/api/client";
import type { PlatformMe } from "@/lib/api/schema";
import { loginUrl, logout, onLogoutElsewhere } from "@/lib/auth/session";
import { PLATFORM_ROLE_LABELS } from "@/lib/format";
import { NAV, currentHref } from "@/lib/nav";

const MeContext = createContext<PlatformMe | null>(null);

/** Le profil connecté, pour masquer ce qu'il ne peut pas faire (le serveur revérifie). */
export function useMe(): PlatformMe | null {
  return useContext(MeContext);
}

/**
 * Coque de l'administration (prompt 27, D3) : bandeau ardoise « Administration » toujours
 * visible, menu latéral dès 1024 px, tiroir en dessous, recherche globale au « / ».
 */
export function AdminShell({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<PlatformMe | null>(null);

  useEffect(() => {
    unwrap(api.GET("/api/v1/platform/auth/me")).then(setMe, () => undefined);
    return onLogoutElsewhere(() => window.location.assign(loginUrl()));
  }, []);

  return (
    <SystemHealthProvider>
      <MeContext.Provider value={me}>
        <Frame me={me}>{children}</Frame>
      </MeContext.Provider>
    </SystemHealthProvider>
  );
}

async function signOut() {
  await logout();
  window.location.assign(loginUrl());
}

function Frame({ me, children }: { me: PlatformMe | null; children: ReactNode }) {
  const { state } = useSystemHealth();
  const drawer = useRef<HTMLDialogElement>(null);
  const menuButton = useRef<HTMLButtonElement>(null);
  const pathname = usePathname();

  function openDrawer() {
    drawer.current?.showModal?.();
    drawer.current?.setAttribute("open", "");
  }
  function closeDrawer() {
    drawer.current?.close?.();
    drawer.current?.removeAttribute("open");
    menuButton.current?.focus();
  }

  // Une navigation ferme le tiroir.
  useEffect(() => {
    if (drawer.current?.open) {
      drawer.current.close?.();
      drawer.current.removeAttribute("open");
    }
  }, [pathname]);

  return (
    <div className="min-h-screen">
      <a
        href="#contenu"
        className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:rounded-lg focus:bg-surface focus:px-4 focus:py-2"
      >
        Aller au contenu
      </a>
      <header className="sticky top-0 z-20 bg-admin text-admin-encre">
        <div className="flex min-h-12 flex-wrap items-center gap-x-3 gap-y-1 px-4 py-1.5">
          <button
            ref={menuButton}
            type="button"
            onClick={openDrawer}
            className="inline-flex min-h-10 items-center gap-2 rounded-lg px-2 font-semibold hover:bg-admin-trait lg:hidden"
          >
            <Menu aria-hidden="true" className="size-5" />
            Menu
          </button>
          <Link href="/" className="flex shrink-0 items-center gap-2 font-bold">
            <span className="max-sm:sr-only">CoGes</span>
            <span className="rounded-md border border-admin-trait px-2 py-0.5 text-sm font-semibold tracking-wide uppercase">
              Administration
            </span>
          </Link>
          <div className="ml-auto hidden max-w-md flex-1 text-encre sm:block">
            <GlobalSearch />
          </div>
          {me && (
            <span className="ml-auto hidden text-sm sm:ml-0 md:inline">
              {me.display_name} · {PLATFORM_ROLE_LABELS[me.role] ?? me.role}
            </span>
          )}
          <ThemeToggle className="hover:bg-admin-trait max-sm:hidden" />
          <button
            type="button"
            onClick={() => void signOut()}
            className="ml-auto inline-flex min-h-10 items-center gap-2 rounded-lg px-2 text-sm font-semibold hover:bg-admin-trait sm:ml-0"
          >
            <LogOut aria-hidden="true" className="size-4" />
            <span className="max-sm:sr-only">Se déconnecter</span>
          </button>
        </div>
        {/* Sur téléphone, la bascule du thème descend ici : la barre du haut reste sur une ligne. */}
        <div className="flex items-center gap-2 px-4 pb-1.5 md:hidden">
          {me && (
            <p className="text-sm">
              {me.display_name} · {PLATFORM_ROLE_LABELS[me.role] ?? me.role}
            </p>
          )}
          <ThemeToggle className="-my-2 ml-auto hover:bg-admin-trait sm:hidden" />
        </div>
        <div className="px-4 pb-2 text-encre sm:hidden">
          <GlobalSearch />
        </div>
      </header>
      <SystemAlert state={state} />

      <div className="lg:flex lg:min-h-[calc(100vh-3rem)]">
        <aside className="hidden w-60 shrink-0 border-r border-trait bg-surface lg:block">
          <div className="sticky top-12 p-3">
            <Navigation me={me} down={state.kind === "down"} />
          </div>
        </aside>
        <main id="contenu" tabIndex={-1} className="min-w-0 flex-1 px-4 py-6 lg:px-8">
          <div className="mx-auto max-w-6xl">{children}</div>
        </main>
      </div>

      <dialog
        ref={drawer}
        aria-label="Menu"
        onCancel={(event) => {
          event.preventDefault();
          closeDrawer();
        }}
        className="m-0 h-full max-h-none w-72 max-w-[85vw] border-r border-trait bg-surface p-0 text-encre backdrop:bg-ombre/50"
      >
        <div className="flex items-center justify-between border-b border-trait px-4 py-3">
          <span className="font-bold">Menu</span>
          <button
            type="button"
            onClick={closeDrawer}
            aria-label="Fermer le menu"
            className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg hover:bg-voile"
          >
            <X aria-hidden="true" className="size-5" />
          </button>
        </div>
        <div className="p-3">
          <Navigation me={me} down={state.kind === "down"} onNavigate={closeDrawer} />
        </div>
      </dialog>
    </div>
  );
}

function Navigation({
  me,
  down,
  onNavigate,
}: {
  me: PlatformMe | null;
  down: boolean;
  onNavigate?: () => void;
}) {
  const pathname = usePathname();
  const current = currentHref(pathname);
  return (
    <nav aria-label="Navigation principale" className="space-y-5">
      {NAV.map((group) => (
        <div key={group.title}>
          <p className="px-3 pb-1 text-sm font-semibold tracking-wide text-encre-douce uppercase">
            {group.title}
          </p>
          <ul className="space-y-0.5">
            {group.items
              .filter((item) => !item.roles || (me && item.roles.includes(me.role)))
              .map((item) => {
                const Icon = item.icon;
                const isCurrent = current === item.href;
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      onClick={onNavigate}
                      aria-current={isCurrent ? "page" : undefined}
                      aria-describedby={
                        item.href === "/system" && down ? "systeme-en-panne" : undefined
                      }
                      className={`flex min-h-11 items-center gap-3 rounded-lg px-3 font-semibold ${
                        isCurrent
                          ? "bg-accent-teinte text-succes"
                          : "text-encre-douce hover:bg-voile hover:text-encre"
                      }`}
                    >
                      <Icon aria-hidden="true" className="size-5 shrink-0" />
                      <span className="flex-1">{item.label}</span>
                      {item.href === "/system" && down && (
                        <span className="inline-flex items-center gap-1.5 text-sm text-danger">
                          <span aria-hidden="true" className="size-2.5 rounded-full bg-danger" />
                          <span id="systeme-en-panne" className="sr-only">
                            en panne
                          </span>
                        </span>
                      )}
                    </Link>
                  </li>
                );
              })}
          </ul>
        </div>
      ))}
    </nav>
  );
}
