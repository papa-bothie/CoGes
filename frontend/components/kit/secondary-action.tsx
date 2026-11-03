import Link from "next/link";
import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

/**
 * Action secondaire de la maquette v2 (prompt 34, bloc F, ADR 0110) : pilule bordée de 2 px,
 * 48 px de haut au moins, texte gras. Remplace les liens d'action soulignés ou discrets
 * (« Toutes les dettes », « Gérer les types de dépenses »…). Un lien **dans une phrase**, un
 * nom dans une liste ou un retour (`BackLink`) n'en est pas une : ils gardent leur forme.
 */
export const secondaryActionClasses = cn(
  "inline-flex min-h-cible items-center justify-center gap-2 self-start rounded-full border-2 border-input bg-card px-[18px] text-corps font-bold text-foreground",
  "outline-none hover:bg-voile focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50",
);

export function SecondaryAction({
  className,
  type = "button",
  ...props
}: ComponentProps<"button">) {
  return <button type={type} className={cn(secondaryActionClasses, className)} {...props} />;
}

export function SecondaryLink({ className, ...props }: ComponentProps<typeof Link>) {
  return <Link className={cn(secondaryActionClasses, className)} {...props} />;
}
