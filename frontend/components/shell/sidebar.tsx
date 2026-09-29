"use client";

import { Store } from "lucide-react";
import Link from "next/link";

import { labels } from "@/lib/labels";
import { isActive, NAV_ITEMS } from "@/lib/navigation";
import { filterByPermission } from "@/lib/permissions";
import { cn } from "@/lib/utils";

const APP_VERSION = process.env.NEXT_PUBLIC_APP_VERSION ?? "dev";

/**
 * Contenu de la barre latérale : logo, **nom de l'entreprise sans sélecteur** (un compte
 * = une entreprise en V1), navigation filtrée par permissions, version en pied.
 */
export function SidebarContent({
  companyName,
  permissions,
  pathname,
  onNavigate,
}: {
  companyName: string;
  permissions: readonly string[];
  pathname: string;
  onNavigate?: () => void;
}) {
  const items = filterByPermission(NAV_ITEMS, permissions);
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2.5 px-3 pt-5 pb-4">
        <div className="grid size-9 place-items-center rounded-lg bg-primary text-primary-foreground">
          <Store className="size-5" aria-hidden />
        </div>
        <div className="min-w-0">
          <p className="text-lg leading-tight font-bold">{labels.app.name}</p>
          <p className="truncate text-xs text-muted-foreground" title={companyName}>
            {companyName}
          </p>
        </div>
      </div>

      <nav aria-label={labels.nav.mainNavigation} className="flex-1 overflow-y-auto px-2 py-2">
        <ul className="space-y-1">
          {items.map((item) => {
            const active = isActive(pathname, item.href);
            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  onClick={onNavigate}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                    active
                      ? "bg-primary text-primary-foreground"
                      : "text-muted-foreground hover:bg-secondary hover:text-foreground",
                  )}
                >
                  <item.icon className="size-4 shrink-0" aria-hidden />
                  {item.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      <p className="border-t px-4 py-3 text-xs text-muted-foreground">
        {labels.app.version(APP_VERSION)}
      </p>
    </div>
  );
}
