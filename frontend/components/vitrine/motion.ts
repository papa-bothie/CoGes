import type { CSSProperties } from "react";

import { cn } from "@/lib/utils";

import styles from "./vitrine.module.css";

export { styles as motion };

/**
 * Propriétés d'un élément qui apparaît au défilement (prompt 38, A2) : `data-revele` pour
 * `<Revele />`, la classe du module pour le CSS, et `--i` pour décaler de 80 ms les cartes
 * voisines. Jamais sur le hero ni sur ce qui est visible au premier affichage.
 */
export function revele(
  index = 0,
  variant: "monte" | "gauche" | "droite" = "monte",
  className?: string,
): { className: string; "data-revele": string; style: CSSProperties } {
  return {
    className: cn(styles.revele, className),
    "data-revele": variant,
    style: { "--i": index } as CSSProperties,
  };
}
