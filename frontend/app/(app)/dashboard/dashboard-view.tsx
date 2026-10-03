"use client";

import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  Bell,
  Clock,
  HandCoins,
  PackageX,
  Receipt,
  ShoppingCart,
  TrendingUp,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";

import { AlertBanner, type AlertSeverity } from "@/components/alerts/alert-banner";
import { PeriodBarChart } from "@/components/charts/period-bar-chart";
import { ErrorState } from "@/components/error-state";
import { IntelligenceSummaryCard } from "@/components/forecast/intelligence-summary-card";
import { KpiCard } from "@/components/kpi-card";
import { Money } from "@/components/money";
import { PageHeader } from "@/components/page-header";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useCompanyLocale } from "@/hooks/use-me";
import { api, unwrap } from "@/lib/api/client";
import type { Schemas } from "@/lib/api/schema";
import { formatAxisAmount, formatDate, formatDateTime, formatMoney } from "@/lib/format";
import { labels } from "@/lib/labels";

type Alert = Schemas["ActiveAlert"];

/** Où mène une alerte : l'écran qui permet d'agir, faute d'identifiant d'entité dans l'alerte. */
const ALERT_TARGETS: Record<string, { href: string; icon: LucideIcon }> = {
  stock_low: { href: "/inventory", icon: AlertTriangle },
  stock_out: { href: "/inventory", icon: PackageX },
  debt_due: { href: "/finance", icon: Clock },
  sale_cancelled: { href: "/sales?status=cancelled", icon: Receipt },
};

function alertTarget(type: string) {
  return ALERT_TARGETS[type] ?? { href: "/notifications", icon: Bell };
}

type AlertGroup = {
  type: string;
  title: string;
  count: number;
  latest: string;
  severity: AlertSeverity;
};

/**
 * Une ligne par type d'alerte : cinq « Dette échue » identiques empilées noient
 * l'information. Le détail reste dans les notifications.
 */
function groupAlerts(alerts: readonly Alert[]): AlertGroup[] {
  const groups = new Map<string, AlertGroup>();
  for (const alert of alerts) {
    const group = groups.get(alert.type);
    if (!group) {
      groups.set(alert.type, {
        type: alert.type,
        title: alert.title,
        count: 1,
        latest: alert.created_at,
        severity: alert.severity,
      });
    } else {
      group.count += 1;
      if (alert.created_at > group.latest) group.latest = alert.created_at;
      // Un groupe prend la gravité la plus haute de ses alertes.
      if (alert.severity === "critical") group.severity = "critical";
    }
  }
  return [...groups.values()];
}

export function DashboardView() {
  const { timeZone, currency } = useCompanyLocale();
  const query = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => unwrap(api.GET("/api/v1/dashboard")),
  });
  const data = query.data;
  const loading = query.isPending;

  if (query.isError) {
    return (
      <>
        <PageHeader title={labels.nav.dashboard} />
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title={labels.nav.dashboard}
        count={
          data ? labels.dashboard.computedAt(formatDateTime(data.computed_at, timeZone)) : undefined
        }
      />

      {data && (data.active_alerts.length > 0 || data.stock_alert_count > 0) && (
        <section aria-label={labels.dashboard.alerts} className="space-y-2">
          {/* Le compteur vient du tableau de bord ; il ne double pas une alerte déjà listée. */}
          {data.stock_alert_count > 0 &&
            !data.active_alerts.some((alert) => alert.type.startsWith("stock_")) && (
              <AlertBanner
                icon={AlertTriangle}
                severity="warning"
                title={labels.dashboard.stockAlertBanner(data.stock_alert_count)}
                detail={labels.dashboard.seeStock}
                href="/inventory"
              />
            )}
          {groupAlerts(data.active_alerts).map((group) => {
            const target = alertTarget(group.type);
            return (
              <AlertBanner
                key={group.type}
                icon={target.icon}
                severity={group.severity}
                title={
                  group.count === 1
                    ? group.title
                    : labels.dashboard.alertGroup(group.title, group.count)
                }
                detail={formatDate(group.latest, timeZone)}
                href={target.href}
              />
            );
          })}
        </section>
      )}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <KpiCard
          label={labels.dashboard.revenueToday}
          value={formatMoney(data?.revenue_today, currency)}
          icon={TrendingUp}
          loading={loading}
        />
        <KpiCard
          label={labels.dashboard.revenueMonth}
          value={formatMoney(data?.revenue_month, currency)}
          hint={
            data &&
            labels.dashboard.monthHint(
              formatDate(data.month_from, timeZone),
              formatDate(data.month_to, timeZone),
            )
          }
          icon={Wallet}
          loading={loading}
        />
        <KpiCard
          label={labels.dashboard.marginMonth}
          value={formatMoney(data?.estimated_margin_month, currency)}
          hint={labels.dashboard.marginHint}
          icon={TrendingUp}
          tone="success"
          loading={loading}
        />
        <KpiCard
          label={labels.dashboard.salesToday}
          value={data ? String(data.sales_today) : "—"}
          icon={ShoppingCart}
          loading={loading}
        />
        <KpiCard
          label={labels.dashboard.receivables}
          value={formatMoney(data?.receivables_open, currency)}
          icon={HandCoins}
          tone="neutral"
          loading={loading}
        />
        <KpiCard
          label={labels.dashboard.stockAlerts}
          value={data ? String(data.stock_alert_count) : "—"}
          hint={data && labels.dashboard.stockAlertsHint(data.stock_alert_count)}
          icon={AlertTriangle}
          tone={data && data.stock_alert_count > 0 ? "warning" : "neutral"}
          loading={loading}
        />
      </div>

      <IntelligenceSummaryCard />

      <div className="grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader>
            <CardTitle>{labels.dashboard.revenueTrend}</CardTitle>
          </CardHeader>
          <CardContent>
            {data ? (
              <PeriodBarChart
                label={labels.dashboard.revenueTrendLabel}
                formatAxis={(value) => formatAxisAmount(value, currency)}
                data={data.revenue_trend.map((point) => ({
                  label: formatDate(point.day, timeZone).slice(0, 5),
                  y: Number(point.net_revenue),
                  display: formatMoney(point.net_revenue, currency),
                }))}
              />
            ) : (
              <Skeleton className="h-[260px] w-full" />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>{labels.dashboard.recentSales}</CardTitle>
            <CardAction>
              <Link href="/sales" className="text-sm font-medium text-primary hover:underline">
                {labels.dashboard.seeAllSales}
              </Link>
            </CardAction>
          </CardHeader>
          <CardContent>
            {loading ? (
              <div className="space-y-3">
                {Array.from({ length: 5 }, (_, index) => (
                  <Skeleton key={index} className="h-10 w-full" />
                ))}
              </div>
            ) : data && data.recent_sales.length > 0 ? (
              <ul className="-mx-2 divide-y">
                {data.recent_sales.map((sale) => (
                  <li key={sale.id}>
                    <Link
                      href={`/sales/${sale.id}`}
                      className="flex items-center justify-between gap-3 rounded-md px-2 py-2.5 hover:bg-muted/60"
                    >
                      <div className="min-w-0">
                        <p className="font-medium numeric">{sale.sale_no}</p>
                        <p className="truncate text-sm text-muted-foreground">
                          {sale.customer_name ?? labels.dashboard.anonymousCustomer}
                        </p>
                      </div>
                      <div className="text-right">
                        <Money value={sale.total} currency={currency} className="font-medium" />
                        <p className="text-sm numeric text-muted-foreground">
                          {formatDate(sale.sold_at, timeZone)}
                        </p>
                      </div>
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="py-6 text-center text-sm text-muted-foreground">
                {labels.dashboard.noRecentSales}
              </p>
            )}
          </CardContent>
        </Card>
      </div>
    </>
  );
}
