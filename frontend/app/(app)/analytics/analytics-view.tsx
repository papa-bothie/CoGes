"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Info, SearchX } from "lucide-react";
import Link from "next/link";

import { AreaChart } from "@/components/charts/area-chart";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { ForecastMeta } from "@/components/forecast/forecast-meta";
import { PageHeader } from "@/components/page-header";
import { PeriodPicker } from "@/components/period/period-picker";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useCompanyLocale } from "@/hooks/use-me";
import { usePeriod } from "@/hooks/use-period";
import { useTableParams } from "@/hooks/use-table-params";
import { api, unwrap } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { formatAxisAmount, formatDate, formatDateTime, formatMoney } from "@/lib/format";
import { labels } from "@/lib/labels";
import { formatMetricValue, METRIC_TEXTS, METRICS, type ProductMetric } from "@/lib/metrics";

type Ranking = Schemas["ProductRanking"];

function isMetric(value: string | null): value is ProductMetric {
  return value !== null && (METRICS as readonly string[]).includes(value);
}

/**
 * Analytics : un classement par **une** métrique choisie (jamais un score combiné), la
 * métrique nommée sur chaque ligne, et les séries de CA et de marge. La métrique et la
 * période vivent dans l'URL.
 */
export function AnalyticsView() {
  const table = useTableParams();
  const period = usePeriod();
  const requested = table.get("metric");
  const metric: ProductMetric = isMetric(requested) ? requested : "revenue";
  const texts = METRIC_TEXTS[metric];

  return (
    <>
      <PageHeader title={labels.nav.analytics} actions={<PeriodPicker />} />

      <div className="flex flex-wrap items-center gap-2">
        <Select
          value={metric}
          onValueChange={(value) => table.update({ metric: value === "revenue" ? null : value })}
        >
          <SelectTrigger aria-label={labels.analytics.metric} className="w-72">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {METRICS.map((value) => (
              <SelectItem key={value} value={value} title={METRIC_TEXTS[value].definition}>
                {METRIC_TEXTS[value].label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              aria-label={labels.analytics.metricHelp}
              className="grid size-8 place-items-center rounded-md text-muted-foreground outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              <Info className="size-4" aria-hidden />
            </button>
          </TooltipTrigger>
          <TooltipContent className="max-w-xs">{labels.analytics.metricHelp}</TooltipContent>
        </Tooltip>
        <p className="text-sm text-muted-foreground" data-testid="metric-definition">
          {texts.definition}
        </p>
      </div>

      <RankingCard metric={metric} from={period.from} to={period.to} />

      <div className="grid gap-4 xl:grid-cols-2">
        <SeriesCard measure="revenue" from={period.from} to={period.to} />
        <SeriesCard measure="margin" from={period.from} to={period.to} />
      </div>
    </>
  );
}

function RankingCard({ metric, from, to }: { metric: ProductMetric; from: string; to: string }) {
  const { currency, timeZone } = useCompanyLocale();
  const params = { metric, from, to, limit: 10 };
  const query = useQuery({
    queryKey: queryKeys.analytics.products(params),
    queryFn: () => unwrap(api.GET("/api/v1/analytics/products", { params: { query: params } })),
    placeholderData: keepPreviousData,
  });
  const data: Ranking | undefined = query.data;
  // Tant que la nouvelle métrique n'est pas arrivée, on n'affiche pas l'ancienne sous
  // le nouveau nom : le libellé vient **de la réponse**.
  const current = data && data.metric === metric ? data : undefined;
  const isForecast = metric === "future_potential";
  const t = labels.analytics;

  return (
    <Card>
      <CardHeader>
        <CardTitle data-testid="ranking-title">
          {current ? t.ranking(current.metric_label) : <Skeleton className="h-5 w-64" />}
        </CardTitle>
        {current && (
          <CardDescription>
            {current.forecast_as_of && current.horizon_days
              ? t.forecastHint(formatDate(current.forecast_as_of), current.horizon_days)
              : t.rankingHint(formatDate(current.period_from), formatDate(current.period_to))}
          </CardDescription>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        {query.isError ? (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        ) : !current ? (
          <Skeleton className="h-72 w-full" />
        ) : current.unavailable_reason ? (
          <EmptyState
            icon={SearchX}
            title={t.insufficient}
            description={current.unavailable_reason}
          />
        ) : current.items.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">{t.empty}</p>
        ) : (
          <>
            <p className="text-sm font-medium" data-testid="ranking-leader">
              {METRIC_TEXTS[metric].leader(`« ${current.items[0]!.product_name} »`)}
            </p>
            {isForecast && current.computed_at && (
              <div className="rounded-lg border bg-muted/30 p-3">
                <ForecastMeta
                  metric={current.metric_label}
                  computedAt={formatDateTime(current.computed_at, timeZone)}
                  model={modelOf(current.items[0])}
                  uncertainty={labels.forecast.intervalPerRow}
                />
              </div>
            )}
            <div className="overflow-x-auto rounded-lg border">
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="w-16 px-4">{t.columns.rank}</TableHead>
                    <TableHead className="px-4">{t.columns.product}</TableHead>
                    <TableHead className="px-4">{t.columns.metric}</TableHead>
                    <TableHead className="px-4 text-right">{t.columns.value}</TableHead>
                    {isForecast && (
                      <>
                        <TableHead className="px-4 text-right">{t.columns.interval}</TableHead>
                        <TableHead className="px-4">{t.columns.model}</TableHead>
                      </>
                    )}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {current.items.map((row, index) => (
                    <TableRow key={row.product_id}>
                      <TableCell className="px-4 numeric text-muted-foreground">
                        {index + 1}
                      </TableCell>
                      <TableCell className="px-4">
                        <Link
                          href={`/products/${row.product_id}`}
                          className="font-medium hover:underline"
                        >
                          {row.product_name}
                        </Link>
                      </TableCell>
                      <TableCell className="px-4 text-muted-foreground">
                        {current.metric_label}
                      </TableCell>
                      <TableCell className="px-4 text-right font-medium numeric whitespace-nowrap">
                        {formatMetricValue(row.value, current.unit, currency, {
                          estimate: isForecast,
                        })}
                      </TableCell>
                      {isForecast && (
                        <>
                          <TableCell className="px-4 text-right numeric whitespace-nowrap text-muted-foreground">
                            {row.lower && row.upper
                              ? t.intervalRange(
                                  formatMetricValue(row.lower, current.unit, currency, {
                                    estimate: true,
                                  }),
                                  formatMetricValue(row.upper, current.unit, currency, {
                                    estimate: true,
                                  }),
                                )
                              : labels.forecast.noInterval}
                          </TableCell>
                          <TableCell className="px-4 text-muted-foreground">
                            {modelOf(row)}
                          </TableCell>
                        </>
                      )}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

function modelOf(row: Schemas["ProductRankRow"] | undefined): string {
  if (!row?.model_name) return "—";
  return row.model_version ? `${row.model_name} v${row.model_version}` : row.model_name;
}

function SeriesCard({
  measure,
  from,
  to,
}: {
  measure: Schemas["TimeseriesMeasure"];
  from: string;
  to: string;
}) {
  const { currency } = useCompanyLocale();
  const params = { measure, from, to };
  const query = useQuery({
    queryKey: queryKeys.analytics.series(params),
    queryFn: () => unwrap(api.GET("/api/v1/analytics/timeseries", { params: { query: params } })),
    placeholderData: keepPreviousData,
  });
  const t = labels.analytics.series;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t[measure]}</CardTitle>
      </CardHeader>
      <CardContent>
        {query.isError ? (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        ) : !query.data ? (
          <Skeleton className="h-[260px] w-full" />
        ) : query.data.points.length === 0 ? (
          <p className="py-10 text-center text-sm text-muted-foreground">{t.empty}</p>
        ) : (
          <AreaChart
            label={measure === "revenue" ? t.revenueLabel : t.marginLabel}
            formatAxis={(value) => formatAxisAmount(value, currency)}
            data={query.data.points.map((point) => ({
              label: formatDate(point.day).slice(0, 5),
              y: Number(point.value),
              display: formatMoney(point.value, currency),
            }))}
          />
        )}
      </CardContent>
    </Card>
  );
}
