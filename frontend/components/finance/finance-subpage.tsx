import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

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
      <Link
        href={backHref}
        className="inline-flex min-h-11 items-center gap-2 self-start font-bold text-foreground hover:underline pointer-coarse:min-h-12"
      >
        <ArrowLeft className="size-[22px]" aria-hidden />
        {backLabel}
      </Link>
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-titre-page leading-[1.45] tracking-[-0.01em]">{title}</h1>
        {actions}
      </div>
      {children}
    </div>
  );
}
