import type { LucideIcon } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { BrandHeader, BrandMark } from "@/components/brand/brand";
import { labels } from "@/lib/labels";
import { cn } from "@/lib/utils";

import type { Rubrique } from "./rubrique";

export type BarItem = {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Couleur de l'onglet actif ; `undefined` = neutre (Réglages). */
  rubrique?: Rubrique;
  active: boolean;
};

const ACTIVE_TAB: Record<Rubrique | "neutre", string> = {
  ventes: "bg-ventes-teinte text-ventes-encre",
  stock: "bg-stock-teinte text-stock-encre",
  argent: "bg-argent-teinte text-argent-encre",
  clients: "bg-clients-teinte text-clients-encre",
  depenses: "bg-depenses-teinte text-depenses-encre",
  conseils: "bg-conseils-teinte text-conseils-encre",
  neutre: "bg-voile text-foreground",
};

/**
 * Barre du haut de la maquette v2 (01) : logo + nom de la boutique à gauche, onglets de
 * 48 px dont l'actif prend la teinte de sa rubrique, puis les boutons de fin (alertes, thème).
 * Au-dessous de 768 px, seuls le logo, le nom court et les boutons restent : la navigation
 * passe dans la barre basse.
 */
export function TopBar({
  companyName,
  items,
  trailing,
}: {
  companyName: string;
  items: readonly BarItem[];
  trailing?: ReactNode;
}) {
  return (
    <header className="border-b border-border bg-card">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 md:px-marge-page">
        <div className="mr-auto min-w-0">
          <div className="hidden md:block">
            <BrandHeader companyName={companyName} />
          </div>
          <div className="flex items-center gap-2.5 md:hidden">
            <BrandMark />
            <span className="truncate font-bold">{companyName}</span>
          </div>
        </div>
        <nav aria-label={labels.kit.nav.mainMenu} className="hidden md:block">
          <ul className="flex flex-wrap gap-1.5">
            {items.map((item) => (
              <li key={item.href}>
                <TabLink item={item} />
              </li>
            ))}
          </ul>
        </nav>
        {trailing && <div className="flex items-center gap-1.5">{trailing}</div>}
      </div>
    </header>
  );
}

/** Un onglet de la barre du haut : 48 px, l'actif à la teinte de sa rubrique. */
export function TabLink({ item, className }: { item: BarItem; className?: string }) {
  return (
    <Link
      href={item.href}
      aria-current={item.active ? "page" : undefined}
      className={cn(
        "flex min-h-cible items-center gap-2 rounded-touche px-4 text-corps font-semibold outline-none",
        "focus-visible:ring-3 focus-visible:ring-ring/50",
        item.active
          ? ACTIVE_TAB[item.rubrique ?? "neutre"]
          : "text-encre-2 hover:bg-voile hover:text-foreground",
        className,
      )}
    >
      <item.icon className="size-[22px] shrink-0" aria-hidden />
      {item.label}
    </Link>
  );
}

/**
 * Barre basse du téléphone (maquette 26) : cinq entrées de 64 px, icône au-dessus du
 * libellé, l'active au vert de marque. Affichée seulement sous 768 px.
 */
export function BottomNav({ items }: { items: readonly BarItem[] }) {
  return (
    <nav
      aria-label={labels.kit.nav.mainMenu}
      className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-card px-1 pt-1 pb-[max(8px,env(safe-area-inset-bottom))] md:hidden"
    >
      <ul className="flex">
        {items.map((item) => (
          <li key={item.href} className="flex-1">
            <Link
              href={item.href}
              aria-current={item.active ? "page" : undefined}
              className={cn(
                "flex min-h-16 flex-col items-center justify-center gap-0.5 rounded-touche text-mini font-bold outline-none",
                "focus-visible:ring-3 focus-visible:ring-ring/50",
                item.active ? "text-ventes-encre" : "text-encre-2",
              )}
            >
              <item.icon className="size-[22px]" aria-hidden />
              {item.label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
