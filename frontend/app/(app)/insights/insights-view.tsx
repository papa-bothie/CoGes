"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import {
  Activity,
  ChevronLeft,
  ChevronRight,
  LineChart,
  PackageX,
  PowerOff,
  SearchX,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { KpiCard } from "@/components/kpi-card";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useCompanyLocale } from "@/hooks/use-me";
import { Can } from "@/hooks/use-permission";
import { useTableParams } from "@/hooks/use-table-params";
import { api, unwrap } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries/keys";
import { formatDate, formatDateTime } from "@/lib/format";
import {
  ANOMALY_TYPES,
  type Insight,
  type InsightSeverity,
  type InsightStatus,
  type InsightType,
} from "@/lib/intelligence";
import { labels } from "@/lib/labels";

import { ForecastsTab } from "./forecasts-tab";
import { InsightCard } from "./insight-card";
import { InsightSheet } from "./insight-sheet";

const ALL = "all";
const PAGE_SIZE = 12;
const TYPES = Object.keys(labels.insights.type) as InsightType[];
const SEVERITIES: readonly InsightSeverity[] = ["critical", "warning", "info"];
const STATUSES: readonly InsightStatus[] = ["new", "read", "acknowledged", "dismissed", "resolved"];

/**
 * CoGes Intelligence : résultats **déjà calculés** par le worker (aucune inférence ici),
 * synthèse, recommandations filtrables et prévisions. Désactivée ⇒ l'écran l'explique.
 */
export function InsightsView() {
  const { timeZone } = useCompanyLocale();
  const table = useTableParams();
  const summary = useQuery({
    queryKey: queryKeys.intelligence.summary,
    queryFn: () => unwrap(api.GET("/api/v1/intelligence/summary")),
  });
  const t = labels.insights;
  const tab = table.get("tab") === "forecasts" ? "forecasts" : "insights";

  if (summary.isError) {
    return (
      <>
        <PageHeader title={labels.nav.insights} />
        <ErrorState error={summary.error} onRetry={() => void summary.refetch()} />
      </>
    );
  }
  const data = summary.data;

  if (data && !data.enabled) {
    return (
      <>
        <PageHeader title={labels.nav.insights} />
        <EmptyState
          icon={PowerOff}
          title={t.disabledTitle}
          description={t.disabledBody}
          action={
            <Can permission="company:update">
              <Button asChild variant="outline">
                <Link href="/settings?tab=company">{t.openSettings}</Link>
              </Button>
            </Can>
          }
        />
      </>
    );
  }

  const byType = data?.insights_by_type ?? {};
  const anomalies = ANOMALY_TYPES.reduce((total, type) => total + (byType[type] ?? 0), 0);

  return (
    <>
      <PageHeader
        title={labels.nav.insights}
        count={
          data &&
          (data.last_as_of && data.computed_at
            ? t.lastRun(formatDate(data.last_as_of), formatDateTime(data.computed_at, timeZone))
            : t.neverRun)
        }
      />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          label={t.counters.stockout}
          value={data ? String(byType.stockout_risk ?? 0) : "—"}
          hint={t.countersHint.stockout}
          icon={PackageX}
          tone="danger"
          loading={!data}
        />
        <KpiCard
          label={t.counters.forecasts}
          value={data ? String(data.forecast_products) : "—"}
          hint={t.countersHint.forecasts}
          icon={LineChart}
          loading={!data}
        />
        <KpiCard
          label={t.counters.anomalies}
          value={data ? String(anomalies) : "—"}
          hint={t.countersHint.anomalies}
          icon={Activity}
          tone="warning"
          loading={!data}
        />
        <KpiCard
          label={t.counters.insufficient}
          value={data ? String(data.insufficient_data_products) : "—"}
          hint={t.countersHint.insufficient}
          icon={SearchX}
          tone="neutral"
          loading={!data}
        />
      </div>

      <Tabs
        value={tab}
        onValueChange={(value) =>
          table.replaceAll(value === "forecasts" ? { tab: "forecasts" } : {})
        }
      >
        <TabsList>
          <TabsTrigger value="insights">{t.tabs.insights}</TabsTrigger>
          <TabsTrigger value="forecasts">{t.tabs.forecasts}</TabsTrigger>
        </TabsList>
        <TabsContent value="insights" className="mt-4">
          {tab === "insights" && <InsightsList />}
        </TabsContent>
        <TabsContent value="forecasts" className="mt-4">
          {tab === "forecasts" && <ForecastsTab />}
        </TabsContent>
      </Tabs>
    </>
  );
}

function InsightsList() {
  const table = useTableParams();
  const [open, setOpen] = useState<Insight | null>(null);
  const t = labels.insights;

  // « Nouveaux » par défaut : ce qui reste à traiter. `status=all` lève le filtre.
  const statusParam = table.get("status");
  const status = statusParam === ALL ? null : ((statusParam as InsightStatus | null) ?? "new");
  const type = table.get("type") as InsightType | null;
  const severity = table.get("severity") as InsightSeverity | null;
  const params = {
    page: table.page,
    page_size: PAGE_SIZE,
    status: status ?? undefined,
    type: type ?? undefined,
    severity: severity ?? undefined,
  };
  const query = useQuery({
    queryKey: queryKeys.intelligence.insights(params),
    queryFn: () => unwrap(api.GET("/api/v1/insights", { params: { query: params } })),
    placeholderData: keepPreviousData,
  });
  const pages = Math.max(1, Math.ceil((query.data?.total ?? 0) / PAGE_SIZE));

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Select
          value={status ?? ALL}
          onValueChange={(value) => table.setFilter("status", value === "new" ? null : value)}
        >
          <SelectTrigger aria-label={t.statusFilter} className="w-44">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>{t.allStatuses}</SelectItem>
            {STATUSES.map((value) => (
              <SelectItem key={value} value={value}>
                {t.status[value]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select
          value={type ?? ALL}
          onValueChange={(value) => table.setFilter("type", value === ALL ? null : value)}
        >
          <SelectTrigger aria-label={t.typeFilter} className="w-52">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>{t.allTypes}</SelectItem>
            {TYPES.map((value) => (
              <SelectItem key={value} value={value}>
                {t.type[value]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select
          value={severity ?? ALL}
          onValueChange={(value) => table.setFilter("severity", value === ALL ? null : value)}
        >
          <SelectTrigger aria-label={t.severityFilter} className="w-44">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>{t.allSeverities}</SelectItem>
            {SEVERITIES.map((value) => (
              <SelectItem key={value} value={value}>
                {t.severity[value]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <span className="ml-auto text-sm text-muted-foreground">
          {query.data ? t.count(query.data.total) : null}
        </span>
      </div>

      {query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : !query.data ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} className="h-36" />
          ))}
        </div>
      ) : query.data.items.length === 0 ? (
        <p className="rounded-xl border border-dashed bg-card py-10 text-center text-sm text-muted-foreground">
          {t.empty}
        </p>
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" aria-busy={query.isFetching}>
          {query.data.items.map((insight) => (
            <li key={insight.id} className="flex">
              <InsightCard insight={insight} onOpen={() => setOpen(insight)} />
            </li>
          ))}
        </ul>
      )}

      {pages > 1 && (
        <div className="flex items-center justify-end gap-2 text-sm text-muted-foreground">
          {labels.table.pageOf(table.page, pages)}
          <Button
            variant="outline"
            size="icon-sm"
            aria-label={labels.table.previous}
            disabled={table.page <= 1}
            onClick={() => table.setPage(table.page - 1)}
          >
            <ChevronLeft />
          </Button>
          <Button
            variant="outline"
            size="icon-sm"
            aria-label={labels.table.next}
            disabled={table.page >= pages}
            onClick={() => table.setPage(table.page + 1)}
          >
            <ChevronRight />
          </Button>
        </div>
      )}

      <InsightSheet insight={open} onOpenChange={(next) => !next && setOpen(null)} />
    </div>
  );
}
