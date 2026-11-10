import Link from "next/link";

import { labels } from "@/lib/labels";
import { cn } from "@/lib/utils";

const t = labels.legal;

/**
 * « Conditions d'utilisation et de vente · Confidentialité » (prompt 36, ADR 0117) : pied de
 * la connexion, du mot de passe à choisir, de la vitrine et des textes eux-mêmes. Le futur
 * formulaire d'inscription (lot 30) le reprend tel quel.
 */
export function LegalLinks({ className }: { className?: string }) {
  const link =
    "inline-flex min-h-cible items-center rounded-mini font-semibold underline underline-offset-4 outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/60";
  return (
    <nav aria-label={t.linksLabel} className={cn("text-mini text-encre-2", className)}>
      <ul className="flex flex-wrap items-center gap-x-2">
        <li>
          <Link href="/conditions" className={link}>
            {t.conditions}
          </Link>
        </li>
        <li aria-hidden>·</li>
        <li>
          <Link href="/confidentialite" className={link}>
            {t.privacy}
          </Link>
        </li>
      </ul>
    </nav>
  );
}
