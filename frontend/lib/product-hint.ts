import { labels } from "@/lib/labels";

type Distinguishable = {
  id: string;
  name: string | null | undefined;
  description?: string | null;
  sku?: string | null;
};

const key = (name: string | null | undefined) => (name ?? "").trim().toLocaleLowerCase("fr");

/**
 * Ce qui s'affiche sous le nom d'un article (ADR 0108) : sa description ; sinon, si un autre
 * article **de la même liste** porte le même nom, sa référence, pour que le vendeur ne se
 * trompe jamais d'article ; sinon rien (aucune ligne vide).
 */
export function productHints<T extends Distinguishable>(items: readonly T[]): Map<string, string> {
  const counts = new Map<string, number>();
  for (const item of items) counts.set(key(item.name), (counts.get(key(item.name)) ?? 0) + 1);
  const hints = new Map<string, string>();
  for (const item of items) {
    const description = item.description?.trim();
    if (description) hints.set(item.id, description);
    else if ((counts.get(key(item.name)) ?? 0) > 1 && item.sku)
      hints.set(item.id, labels.products.description.reference(item.sku));
  }
  return hints;
}

/** Nom accessible d'un article, avec ce qui le distingue : « Huile, 5 litres ». */
export function nameWithHint(name: string, hint: string | undefined): string {
  return hint ? `${name}, ${hint}` : name;
}
