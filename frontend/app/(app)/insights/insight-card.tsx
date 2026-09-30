"use client";

import { Badge } from "@/components/ui/badge";
import { useCompanyLocale } from "@/hooks/use-me";
import { formatDate } from "@/lib/format";
import { insightValue, type Insight, type InsightSeverity } from "@/lib/intelligence";
import { labels } from "@/lib/labels";
import { cn } from "@/lib/utils";

export const SEVERITY_VARIANTS: Record<InsightSeverity, "info" | "warning" | "danger"> = {
  info: "info",
  warning: "warning",
  critical: "danger",
};

const SEVERITY_EDGE: Record<InsightSeverity, string> = {
  info: "border-l-primary/40",
  warning: "border-l-warning",
  critical: "border-l-destructive",
};

/**
 * Carte **compacte** (défaut du prototype corrigé : cartes trop hautes) : type, sévérité,
 * titre, métrique et valeur, date de calcul, confiance. Le détail s'ouvre dans le panneau.
 */
export function InsightCard({ insight, onOpen }: { insight: Insight; onOpen: () => void }) {
  const { currency, timeZone } = useCompanyLocale();
  const value = insightValue(insight, currency);
  const t = labels.insights;
  const confidence = insight.insufficient_data
    ? labels.forecast.insufficientData
    : (insight.uncertainty?.level ?? null);

  return (
    <button
      type="button"
      onClick={onOpen}
      className={cn(
        "flex h-full w-full flex-col gap-2 rounded-xl border border-l-4 bg-card p-4 text-left transition-colors outline-none hover:bg-muted/40 focus-visible:ring-3 focus-visible:ring-ring/50",
        SEVERITY_EDGE[insight.severity],
        insight.status !== "new" && "opacity-75",
      )}
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge variant="neutral">{t.type[insight.insight_type]}</Badge>
        <Badge variant={SEVERITY_VARIANTS[insight.severity]}>{t.severity[insight.severity]}</Badge>
        {insight.status !== "new" && <Badge variant="outline">{t.status[insight.status]}</Badge>}
      </div>
      <p className="line-clamp-2 font-medium">{insight.title}</p>
      <dl className="mt-auto grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
        <dt className="text-muted-foreground">{labels.forecast.metric}</dt>
        <dd className="truncate">
          {insight.metric_name ?? "—"}
          {" · "}
          <span className="font-semibold numeric">{value ?? labels.forecast.insufficientData}</span>
        </dd>
        <dt className="text-muted-foreground">{labels.forecast.computedAt}</dt>
        <dd className="numeric">{formatDate(insight.computed_at, timeZone)}</dd>
        {confidence && (
          <>
            <dt className="text-muted-foreground">{t.confidence}</dt>
            <dd>{confidence}</dd>
          </>
        )}
      </dl>
    </button>
  );
}
