"use client";

import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { Schemas } from "@/lib/api/schema";

import { queryKeys } from "./keys";

export type StockLine = Schemas["StockLine"];

/**
 * Stock des articles affichés (`product_id` répété, ADR 0050). Un article absent du
 * résultat n'a encore aucun mouvement : on n'invente pas de quantité pour lui.
 */
export function useStockFor(productIds: readonly string[]) {
  return useQuery({
    queryKey: queryKeys.stock.forProducts(productIds),
    enabled: productIds.length > 0,
    queryFn: async () => {
      const page = await unwrap(
        api.GET("/api/v1/inventory/stock", {
          params: { query: { product_id: [...productIds], page_size: 100 } },
        }),
      );
      return new Map(page.items.map((line) => [line.product_id, line]));
    },
  });
}
