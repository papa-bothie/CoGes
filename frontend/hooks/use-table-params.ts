"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";

/**
 * Page, taille et recherche d'une liste, gardées **dans l'URL** : un lien partagé ou un
 * retour arrière rouvre la même page du tableau. Bornes alignées sur l'API (≤ 100).
 */
export function useTableParams(defaultPageSize = 20) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  const page = Math.max(1, Number(params.get("page")) || 1);
  const pageSize = Math.min(100, Math.max(1, Number(params.get("page_size")) || defaultPageSize));
  const search = params.get("search") ?? "";

  const update = useCallback(
    (changes: Record<string, string | number | null>) => {
      const next = new URLSearchParams(params.toString());
      for (const [key, value] of Object.entries(changes)) {
        if (value === null || value === "") next.delete(key);
        else next.set(key, String(value));
      }
      const query = next.toString();
      router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
    },
    [params, pathname, router],
  );

  return {
    page,
    pageSize,
    search,
    setPage: (value: number) => update({ page: value <= 1 ? null : value }),
    // Une nouvelle recherche repart de la première page.
    setSearch: (value: string) => update({ search: value, page: null }),
    setFilter: (key: string, value: string | null) => update({ [key]: value, page: null }),
    get: (key: string) => params.get(key),
  };
}
