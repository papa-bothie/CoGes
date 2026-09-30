"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { ForecastSeries } from "@/components/forecast/product-forecast";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, unwrap } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { labels } from "@/lib/labels";

type Forecast = Schemas["ForecastRead"];

/** Au plus 5 pages de 100 lignes (≈ 35 produits à 14 jours) : un tableau, pas un export. */
const MAX_PAGES = 5;

async function allDemandForecasts(): Promise<Forecast[]> {
  const rows: Forecast[] = [];
  for (let page = 1; page <= MAX_PAGES; page += 1) {
    const result = await unwrap(
      api.GET("/api/v1/forecasts", {
        params: { query: { type: "demand_qty", page, page_size: 100 } },
      }),
    );
    rows.push(...result.items);
    if (rows.length >= result.total) break;
  }
  return rows;
}

/** Prévisions de demande par produit (ordre du serveur), chacune datée et qualifiée. */
export function ForecastsTab() {
  const query = useQuery({
    queryKey: queryKeys.intelligence.forecasts({ type: "demand_qty", all: true }),
    queryFn: allDemandForecasts,
  });

  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  if (!query.data) {
    return (
      <div className="grid gap-4 lg:grid-cols-2">
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-72" />
        ))}
      </div>
    );
  }
  const byProduct = new Map<string, Forecast[]>();
  for (const row of query.data) {
    const key = row.product_id ?? "";
    byProduct.set(key, [...(byProduct.get(key) ?? []), row]);
  }
  if (byProduct.size === 0) {
    return (
      <EmptyState
        title={labels.forecast.insufficientData}
        description={labels.insights.forecastsEmpty}
      />
    );
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        {labels.insights.forecastsCount(byProduct.size)}
      </p>
      <div className="grid gap-4 lg:grid-cols-2">
        {[...byProduct.entries()].map(([productId, rows]) => (
          <Card key={productId}>
            <CardHeader>
              <CardTitle>
                <Link href={`/products/${productId}`} className="hover:underline">
                  {rows[0]?.product_name}
                </Link>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ForecastSeries rows={rows} />
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
