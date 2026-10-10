import { articleTone } from "@/components/kit/list-row";

/**
 * Les huit couleurs de rayon de la maquette v2 (écran 12), dans l'ordre de sa palette ;
 * `categories.color` en garde le rang (1 à 8, révision 0017). Chacune réutilise une couleur
 * d'article du thème : aucune valeur nouvelle.
 */
export const SHELF_COLORS = [
  { value: 1, label: "Brun", className: "bg-article-1" },
  { value: 2, label: "Moutarde", className: "bg-article-2" },
  { value: 3, label: "Bleu", className: "bg-article-11" },
  { value: 4, label: "Violet", className: "bg-article-6" },
  { value: 5, label: "Bleu-vert", className: "bg-article-3" },
  { value: 6, label: "Vert", className: "bg-article-12" },
  { value: 7, label: "Rose", className: "bg-article-7" },
  { value: 8, label: "Rouge", className: "bg-article-8" },
] as const;

/** Rang de la couleur d'un rayon : la sienne, ou une couleur stable tirée de son nom. */
export function shelfColor(category: { name: string; color?: number | null }): number {
  if (category.color && category.color >= 1 && category.color <= 8) return category.color;
  return ((articleTone(category.name) - 1) % SHELF_COLORS.length) + 1;
}

export function shelfClass(category: { name: string; color?: number | null }): string {
  return SHELF_COLORS[shelfColor(category) - 1]?.className ?? SHELF_COLORS[0].className;
}
