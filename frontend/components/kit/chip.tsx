import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

import { RUBRIQUE_BORDER, RUBRIQUE_CLASSES, type Rubrique } from "./rubrique";

/**
 * Puce de la maquette v2 : pilule bordée de 2 px, 48 px de haut au moins. Choisie, elle
 * prend la teinte de sa rubrique (`tone="teinte"`, filtres et rayons) ou sa couleur pleine
 * (`tone="plein"`, moyens de paiement). Bouton à bascule : `aria-pressed`.
 */
export function Chip({
  selected = false,
  rubrique = "ventes",
  tone = "teinte",
  className,
  type = "button",
  ...props
}: ComponentProps<"button"> & {
  selected?: boolean;
  rubrique?: Rubrique;
  tone?: "teinte" | "plein";
}) {
  const picked =
    tone === "plein"
      ? cn(RUBRIQUE_CLASSES[rubrique].solid, RUBRIQUE_BORDER[rubrique])
      : RUBRIQUE_CLASSES[rubrique].picked;
  return (
    <button
      type={type}
      aria-pressed={selected}
      className={cn(
        "inline-flex min-h-cible items-center justify-center gap-2 rounded-full border-2 px-[18px] text-corps font-bold transition-colors",
        "outline-none focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50",
        selected ? picked : "border-input bg-card text-foreground hover:bg-voile",
        className,
      )}
      {...props}
    />
  );
}
