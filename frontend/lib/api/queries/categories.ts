"use client";

import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { Schemas } from "@/lib/api/schema";

import { queryKeys } from "./keys";

export type Category = Schemas["CategoryRead"];
export type CategoryNode = Category & { depth: number; path: string };

/** Toutes les catégories (une boutique en compte quelques dizaines) : pages de 100 enchaînées. */
export function useCategories() {
  return useQuery({
    queryKey: queryKeys.categories.all,
    staleTime: 5 * 60_000,
    queryFn: async () => {
      const all: Category[] = [];
      for (let page = 1; ; page += 1) {
        const result = await unwrap(
          api.GET("/api/v1/categories", { params: { query: { page, page_size: 100 } } }),
        );
        all.push(...result.items);
        if (all.length >= result.total || result.items.length === 0) break;
      }
      return all;
    },
  });
}

/**
 * Arbre aplati pour l'affichage : parents avant enfants, par ordre alphabétique, avec la
 * profondeur et le chemin (« Boissons › Eaux »). Une catégorie dont le parent est
 * introuvable remonte à la racine plutôt que de disparaître.
 */
export function flattenTree(categories: readonly Category[]): CategoryNode[] {
  const ids = new Set(categories.map((category) => category.id));
  const children = new Map<string | null, Category[]>();
  for (const category of categories) {
    const parent = category.parent_id && ids.has(category.parent_id) ? category.parent_id : null;
    children.set(parent, [...(children.get(parent) ?? []), category]);
  }
  const result: CategoryNode[] = [];
  const visit = (parent: string | null, depth: number, prefix: string, seen: Set<string>) => {
    const level = [...(children.get(parent) ?? [])].sort((a, b) =>
      a.name.localeCompare(b.name, "fr"),
    );
    for (const category of level) {
      if (seen.has(category.id)) continue;
      const path = prefix ? `${prefix} › ${category.name}` : category.name;
      result.push({ ...category, depth, path });
      visit(category.id, depth + 1, path, new Set([...seen, category.id]));
    }
  };
  visit(null, 0, "", new Set());
  return result;
}
