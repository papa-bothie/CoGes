import type { ReactNode } from "react";

import { formatMoney } from "@/lib/format";
import { cn } from "@/lib/utils";

const NNBSP = "\u202f";

/**
 * Montant ou nombre **déjà formaté** dont l'espace fine des milliers est élargie à l'écran :
 * Inter la dessine si étroite qu'en gras et grand corps « 13 000 » se lisait « 13000 ». Le
 * caractère reste dans le texte (copier-coller, lecteurs d'écran, tests inchangés).
 */
export function spacedGroups(text: string): ReactNode {
  if (!text.includes(NNBSP)) return text;
  return text.split(NNBSP).flatMap((part, index) =>
    index === 0
      ? [part]
      : [
          <span key={index} className="tracking-[0.12em]">
            {NNBSP}
          </span>,
          part,
        ],
  );
}

/**
 * Montant tel que l'API l'a renvoyé, formaté sans passer par un `float` : chiffres
 * tabulaires et **jamais** coupé sur deux lignes (défaut du prototype, § 5).
 */
export function Money({
  value,
  currency,
  className,
}: {
  value: string | null | undefined;
  currency?: string;
  className?: string;
}) {
  return (
    <span className={cn("numeric whitespace-nowrap", className)}>
      {spacedGroups(formatMoney(value, currency))}
    </span>
  );
}
