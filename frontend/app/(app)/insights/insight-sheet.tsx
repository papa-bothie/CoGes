"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Loader2 } from "lucide-react";
import Link from "next/link";
import { toast } from "sonner";

import { ForecastMeta } from "@/components/forecast/forecast-meta";
import { ProductForecast } from "@/components/forecast/product-forecast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useCompanyLocale } from "@/hooks/use-me";
import { usePermission } from "@/hooks/use-permission";
import { api, unwrap } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { formatDate, formatDateTime } from "@/lib/format";
import {
  evidenceFacts,
  insightHref,
  insightValue,
  modelLabel,
  uncertaintyLabel,
  type Insight,
} from "@/lib/intelligence";
import { labels } from "@/lib/labels";

import { SEVERITY_VARIANTS } from "./insight-card";

type StatusChange = Schemas["InsightStatusChange"];
const ACTIONS: readonly StatusChange[] = ["read", "acknowledged", "dismissed", "resolved"];

/**
 * Détail d'une recommandation : texte, métrique nommée, date de calcul, modèle, incertitude,
 * éléments du calcul (evidence) et, pour un produit, sa prévision en mini-graphique.
 */
export function InsightSheet({
  insight,
  onOpenChange,
}: {
  insight: Insight | null;
  onOpenChange: (open: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const { currency, timeZone } = useCompanyLocale();
  const canUpdate = usePermission("insights:update");
  const t = labels.insights;

  const update = useMutation({
    mutationFn: ({ id, status }: { id: string; status: StatusChange }) =>
      unwrap(
        api.PATCH("/api/v1/insights/{insight_id}", {
          params: { path: { insight_id: id } },
          body: { status },
        }),
      ),
    onSuccess: (updated) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.intelligence.all });
      toast.success(t.statusChanged(t.status[updated.status]));
      onOpenChange(false);
    },
  });

  const value = insight ? insightValue(insight, currency) : null;
  const href = insight ? insightHref(insight) : null;
  const evidence = insight ? evidenceFacts(insight.evidence, currency) : null;

  return (
    <Sheet open={insight !== null} onOpenChange={onOpenChange}>
      <SheetContent className="w-full gap-0 overflow-y-auto sm:max-w-lg">
        {insight && evidence && (
          <>
            <SheetHeader className="border-b">
              <div className="flex flex-wrap gap-1.5 pr-8">
                <Badge variant="neutral">{t.type[insight.insight_type]}</Badge>
                <Badge variant={SEVERITY_VARIANTS[insight.severity]}>
                  {t.severity[insight.severity]}
                </Badge>
                <Badge variant="outline">{t.status[insight.status]}</Badge>
              </div>
              <SheetTitle className="text-base">{insight.title}</SheetTitle>
              {insight.body && <SheetDescription>{insight.body}</SheetDescription>}
            </SheetHeader>

            <div className="space-y-6 p-4">
              <section className="space-y-2 rounded-lg border bg-muted/30 p-3">
                <p className="text-2xl font-bold numeric">
                  {value ?? (
                    <span className="text-base text-muted-foreground">
                      {labels.forecast.insufficientData}
                    </span>
                  )}
                </p>
                <ForecastMeta
                  metric={insight.metric_name ?? "—"}
                  computedAt={formatDateTime(insight.computed_at, timeZone)}
                  model={modelLabel(insight.model_name, insight.model_version) ?? t.noModel}
                  uncertainty={
                    insight.insufficient_data
                      ? labels.forecast.insufficientData
                      : uncertaintyLabel(insight.uncertainty, insight.unit)
                  }
                />
                {insight.valid_until && (
                  <p className="text-xs text-muted-foreground">
                    {t.validUntil(formatDate(insight.valid_until, timeZone))}
                  </p>
                )}
              </section>

              {insight.entity_table === "products" &&
                insight.entity_id &&
                !insight.insufficient_data && (
                  <section className="space-y-2">
                    <h3 className="text-sm font-semibold">{t.forecast}</h3>
                    <ProductForecast productId={insight.entity_id} />
                  </section>
                )}

              {evidence.facts.length > 0 && (
                <section className="space-y-2">
                  <h3 className="text-sm font-semibold">{t.evidence}</h3>
                  <dl className="grid grid-cols-[minmax(9rem,40%)_1fr] gap-x-4 gap-y-1 text-sm">
                    {evidence.facts.map((fact) => (
                      <div key={fact.key} className="contents">
                        <dt className="text-muted-foreground">{fact.label}</dt>
                        <dd className="numeric">{fact.value}</dd>
                      </div>
                    ))}
                  </dl>
                </section>
              )}
              {evidence.thresholds.length > 0 && (
                <section className="space-y-2">
                  <h3 className="text-sm font-semibold">{t.thresholds}</h3>
                  <dl className="grid grid-cols-[minmax(9rem,40%)_1fr] gap-x-4 gap-y-1 text-sm">
                    {evidence.thresholds.map((fact) => (
                      <div key={fact.key} className="contents">
                        <dt className="text-muted-foreground">{fact.label}</dt>
                        <dd className="numeric">{fact.value}</dd>
                      </div>
                    ))}
                  </dl>
                </section>
              )}

              {href && (
                <Link
                  href={href}
                  className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
                >
                  {t.seeItem}
                  <ArrowRight className="size-4" aria-hidden />
                </Link>
              )}

              {canUpdate && (
                <div className="flex flex-wrap gap-2 border-t pt-4">
                  {ACTIONS.filter((status) => status !== insight.status).map((status) => (
                    <Button
                      key={status}
                      variant={status === "dismissed" ? "outline" : "secondary"}
                      size="sm"
                      disabled={update.isPending}
                      onClick={() => update.mutate({ id: insight.id, status })}
                    >
                      {update.isPending && update.variables?.status === status && (
                        <Loader2 className="animate-spin" aria-hidden />
                      )}
                      {t.actions[status]}
                    </Button>
                  ))}
                </div>
              )}
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
