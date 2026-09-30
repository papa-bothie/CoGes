"use client";

import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";

import { queryKeys } from "./keys";

export function useProduct(productId: string) {
  return useQuery({
    queryKey: queryKeys.products.detail(productId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/products/{product_id}", { params: { path: { product_id: productId } } }),
      ),
  });
}
