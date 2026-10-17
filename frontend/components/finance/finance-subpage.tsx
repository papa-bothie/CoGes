import type { ReactNode } from "react";

import { BackLink } from "@/components/back-link";
import { labels } from "@/lib/labels";

/**
 * Gabarit des pages secondaires de L'argent (« Toutes les dettes », « Toutes les
 * dépenses ») : retour, titre, actions à droite. Les écrans de la maquette restent
 * l'entrée ; ces pages gardent ce qu'elle ne montre pas (ADR 0073).
 */
export function FinanceSubpage({
  title,
  backHref = "/finance",
  backLabel = labels.moneyScreens.title,
  actions,
  children,
}: {
  title: string;
  backHref?: string;
  backLabel?: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="mx-auto flex max-w-page flex-col gap-5">
      <BackLink fixed fallback={{ href: backHref, label: backLabel }} />
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-titre-page leading-[1.45] tracking-[-0.01em]">{title}</h1>
        {actions}
      </div>
      {children}
    </div>
  );
}
