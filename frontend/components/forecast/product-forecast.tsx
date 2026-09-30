"use client";

import { useQuery } from "@tanstack/react-query";

import { Skeleton } from "@/components/ui/skeleton";
import { useCompanyLocale } from "@/hooks/use-me";
import { api, unwrap } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { formatDate, formatDateTime, formatQty } from "@/lib/format";
import { modelLabel, uncertaintyLabel } from "@/lib/intelligence";
import { labels } from "@/lib/labels";

import { ForecastBandChart } from "./forecast-band-chart";
import { ForecastMeta } from "./forecast-meta";

type Forecast = Schemas["ForecastRead"];

/**
 * Prévision de demande d'un lot de lignes (un produit, jour par jour) : graphique avec
 * bande d'incertitude **et toujours** date de calcul, modèle et version, incertitude.
 */
export function ForecastSeries({ rows }: { rows: readonly Forecast[] }) {
  const { timeZone } = useCompanyLocale();
  const first = rows[0];
  if (!first) return null;
  return (
    <div className="space-y-3">
      <ForecastBandChart
        label={labels.insights.forecastChart(first.product_name ?? "")}
        data={rows.map((row) => ({
          label: formatDate(row.horizon_date).slice(0, 5),
          y: Number(row.value),
          band:
            row.uncertainty.lower !== null && row.uncertainty.upper !== null
              ? [Number(row.uncertainty.lower), Number(row.uncertainty.upper)]
              : null,
          display: `${formatQty(row.value)} ${row.unit}`,
          interval: uncertaintyLabel({ ...row.uncertainty, level: null }, row.unit),
        }))}
      />
      <ForecastMeta
        metric={`${first.metric_name} (${first.unit})`}
        computedAt={formatDateTime(first.computed_at, timeZone)}
        model={modelLabel(first.model_name, first.model_version) ?? "—"}
        uncertainty={first.uncertainty.level ?? uncertaintyLabel(first.uncertainty, first.unit)}
      />
      <p className="text-xs text-muted-foreground">
        {labels.insights.forecastAsOf(formatDate(first.as_of), rows.length)}
      </p>
    </div>
  );
}

/** Prévision d'un produit, lue sur `GET /forecasts?product_id=` ; jamais recalculée ici. */
export function ProductForecast({ productId }: { productId: string }) {
  const params = { product_id: productId, type: "demand_qty" as const, page_size: 100 };
  const query = useQuery({
    queryKey: queryKeys.intelligence.forecasts(params),
    queryFn: () => unwrap(api.GET("/api/v1/forecasts", { params: { query: params } })),
  });
  if (query.isPending) return <Skeleton className="h-40 w-full" />;
  if (query.isError || !query.data.enabled) return null;
  if (query.data.insufficient_data || query.data.items.length === 0) {
    return <p className="text-sm text-muted-foreground">{labels.insights.noForecast}</p>;
  }
  return <ForecastSeries rows={query.data.items} />;
}
