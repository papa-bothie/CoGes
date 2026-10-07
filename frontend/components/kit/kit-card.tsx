import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * Carte de la maquette v2 : fond blanc, bordure 1 px, rayon 22 px, marge intérieure 22 px.
 * Titre en h2 (20 px, gras 700) et action facultative à droite (« Tout voir »).
 */
export function KitCard({
  title,
  action,
  children,
  className,
  headingLevel = 2,
}: {
  title?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  headingLevel?: 2 | 3;
}) {
  const Heading = headingLevel === 2 ? "h2" : "h3";
  return (
    <section
      className={cn(
        "rounded-carte border border-border bg-card p-carte text-card-foreground",
        className,
      )}
    >
      {(title || action) && (
        <div className="mb-4 flex items-center justify-between gap-4">
          {title && <Heading className="text-titre-carte">{title}</Heading>}
          {action}
        </div>
      )}
      {children}
    </section>
  );
}
