"use client";

import { useQuery } from "@tanstack/react-query";
import {
  ArrowDownLeft,
  ArrowUpRight,
  Calculator,
  HandCoins,
  Landmark,
  PiggyBank,
  Receipt,
  Scale,
  TrendingUp,
  Truck,
} from "lucide-react";

import { CashFlowChart } from "@/components/charts/cash-flow-chart";
import { ErrorState } from "@/components/error-state";
import { KpiCard } from "@/components/kpi-card";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useCompanyLocale } from "@/hooks/use-me";
import { usePeriod } from "@/hooks/use-period";
import { api, unwrap } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries/keys";
import { compareDecimal } from "@/lib/decimal";
import { formatAxisAmount, formatDate, formatMoney } from "@/lib/format";
import { labels } from "@/lib/labels";

/**
 * Vue d'ensemble de `GET /analytics/overview` : chaque carte reprend un champ de l'API,
 * sans addition ni soustraction côté navigateur (ADR 0030, 0034).
 */
export function OverviewTab() {
  const { currency } = useCompanyLocale();
  const period = usePeriod();
  const params = { from: period.from, to: period.to };
  const query = useQuery({
    queryKey: queryKeys.analytics.overview(params),
    queryFn: () => unwrap(api.GET("/api/v1/analytics/overview", { params: { query: params } })),
  });
  const data = query.data;
  const loading = query.isPending;
  const t = labels.finance.overview;
  const money = (value: string | undefined) => formatMoney(value, currency);
  const tone = (value: string | undefined) =>
    value !== undefined && compareDecimal(value, "0") === -1 ? "danger" : "success";

  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;

  return (
    <>
      <section aria-labelledby="cash" className="space-y-3">
        <h2 id="cash" className="text-sm font-medium text-muted-foreground">
          {t.sections.cash}
        </h2>
        <div className="grid gap-4 sm:grid-cols-3">
          <KpiCard
            label={t.cashIn}
            value={money(data?.cash_in)}
            hint={t.cashHint}
            icon={ArrowDownLeft}
            tone="success"
            loading={loading}
          />
          <KpiCard
            label={t.cashOut}
            value={money(data?.cash_out)}
            icon={ArrowUpRight}
            tone="neutral"
            loading={loading}
          />
          <KpiCard
            label={t.netCash}
            value={money(data?.net_cash)}
            icon={Landmark}
            tone={tone(data?.net_cash)}
            loading={loading}
          />
        </div>
      </section>
      <section aria-labelledby="profit" className="space-y-3">
        <h2 id="profit" className="text-sm font-medium text-muted-foreground">
          {t.sections.profit}
        </h2>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
          <KpiCard
            label={t.netRevenue}
            value={money(data?.net_revenue)}
            hint={data && t.netRevenueHint(data.sale_count)}
            icon={TrendingUp}
            loading={loading}
          />
          <KpiCard
            label={t.cogs}
            value={money(data?.cogs_net)}
            hint={t.cogsHint}
            icon={Receipt}
            tone="neutral"
            loading={loading}
          />
          <KpiCard
            label={t.grossMargin}
            value={money(data?.gross_margin)}
            hint={t.grossMarginHint}
            icon={Calculator}
            tone={tone(data?.gross_margin)}
            loading={loading}
          />
          <KpiCard
            label={t.expenses}
            value={money(data?.expenses_total)}
            hint={data && t.expensesHint(money(data.fixed_expenses), money(data.variable_expenses))}
            icon={PiggyBank}
            tone="neutral"
            loading={loading}
          />
          <KpiCard
            label={t.result}
            value={money(data?.estimated_result)}
            hint={t.resultHint}
            icon={Scale}
            tone={tone(data?.estimated_result)}
            loading={loading}
          />
        </div>
      </section>
      <section aria-labelledby="open" className="space-y-3">
        <h2 id="open" className="text-sm font-medium text-muted-foreground">
          {t.sections.open}
        </h2>
        <div className="grid gap-4 sm:grid-cols-2">
          <KpiCard
            label={t.receivables}
            value={money(data?.receivables_open)}
            hint={t.openHint}
            icon={HandCoins}
            tone="warning"
            loading={loading}
          />
          <KpiCard
            label={t.payables}
            value={money(data?.payables_open)}
            hint={t.openHint}
            icon={Truck}
            tone="warning"
            loading={loading}
          />
        </div>
      </section>

      <Card>
        <CardHeader>
          <CardTitle>{t.cashFlow}</CardTitle>
        </CardHeader>
        <CardContent>
          {!data ? (
            <Skeleton className="h-[290px] w-full" />
          ) : data.daily.length === 0 ? (
            <p className="py-10 text-center text-sm text-muted-foreground">{t.noCash}</p>
          ) : (
            <CashFlowChart
              label={t.cashFlowLabel}
              seriesLabels={{ inflow: t.cashIn, outflow: t.cashOut }}
              formatAxis={(value) => formatAxisAmount(value, currency)}
              data={data.daily.map((point) => ({
                label: formatDate(point.day).slice(0, 5),
                inflow: Number(point.cash_in),
                outflow: Number(point.cash_out),
                inflowDisplay: money(point.cash_in),
                outflowDisplay: money(point.cash_out),
              }))}
            />
          )}
        </CardContent>
      </Card>
    </>
  );
}
