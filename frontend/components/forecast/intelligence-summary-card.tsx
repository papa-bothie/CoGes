"use client";

import { useQuery } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import Link from "next/link";

import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useCompanyLocale } from "@/hooks/use-me";
import { usePermission } from "@/hooks/use-permission";
import { api, unwrap } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries/keys";
import { formatDate, formatDateTime } from "@/lib/format";
import { labels } from "@/lib/labels";

/**
 * Bloc prédictif du tableau de bord. Il **disparaît** — sans message d'erreur ni place
 * vide — quand l'Intelligence est désactivée, indisponible, ou que l'utilisateur n'a pas
 * le droit de la lire : CoGes fonctionne sans elle (décision 11).
 */
export function IntelligenceSummaryCard() {
  const allowed = usePermission("insights:read");
  const { timeZone } = useCompanyLocale();
  const summary = useQuery({
    queryKey: queryKeys.intelligence.summary,
    queryFn: () => unwrap(api.GET("/api/v1/intelligence/summary")),
    enabled: allowed,
  });
  const data = summary.data;
  if (!allowed || !data || !data.enabled || !data.computed_at || !data.last_as_of) return null;

  const t = labels.insights;
  const bySeverity = data.insights_by_severity;
  const rows: [string, number][] = [
    [t.severity.critical, bySeverity.critical ?? 0],
    [t.severity.warning, bySeverity.warning ?? 0],
    [t.counters.forecasts, data.forecast_products],
    [t.counters.insufficient, data.insufficient_data_products],
  ];

  return (
    <Card data-testid="dashboard-intelligence">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Sparkles className="size-4 text-primary" aria-hidden />
          {t.dashboardTitle}
        </CardTitle>
        <CardAction>
          <Link href="/insights" className="text-sm font-medium text-primary hover:underline">
            {t.dashboardLink}
          </Link>
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-3">
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {rows.map(([label, count]) => (
            <div key={label} className="rounded-lg border px-3 py-2">
              <dt className="text-xs text-muted-foreground">{label}</dt>
              <dd className="text-xl font-semibold numeric">{count}</dd>
            </div>
          ))}
        </dl>
        <p className="text-xs text-muted-foreground">
          {t.lastRun(formatDate(data.last_as_of), formatDateTime(data.computed_at, timeZone))}
        </p>
      </CardContent>
    </Card>
  );
}
