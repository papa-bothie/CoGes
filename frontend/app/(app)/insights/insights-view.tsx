"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Clock,
  Tag,
  TrendingDown,
  TrendingUp,
  Wallet,
  Zap,
  PowerOff,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { Chip } from "@/components/kit/chip";
import { KitCard } from "@/components/kit/kit-card";
import { Skeleton } from "@/components/ui/skeleton";
import { useCompanyLocale } from "@/hooks/use-me";
import { Can, usePermission } from "@/hooks/use-permission";
import { useTableParams } from "@/hooks/use-table-params";
import { withFrom } from "@/lib/back-target";
import { api, unwrap } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { formatAmount, formatClock, formatDate, formatDayMonth, formatQty } from "@/lib/format";
import { modelLabel, type Insight, type InsightType } from "@/lib/intelligence";
import { labels } from "@/lib/labels";
import { addDays, todayIn } from "@/lib/period";
import { qtyWithUnit } from "@/lib/units";
import { cn } from "@/lib/utils";

import { InsightSheet } from "./insight-sheet";

const t = labels.adviceScreens;
type View = "advice" | "best" | "forecasts";
const VIEWS: readonly View[] = ["advice", "best", "forecasts"];

/**
 * Conseils, maquette v2 (écrans 22, 22b, 22c ; ADR 0074) : CoGes Intelligence et le
 * classement des articles réunis. Tout est **déjà calculé** (aucun calcul ici) ; chaque
 * conseil garde sa métrique, sa date, son modèle et son incertitude derrière « Pourquoi ? ».
 */
export function InsightsView() {
  const { timeZone } = useCompanyLocale();
  const table = useTableParams();
  const canReadInsights = usePermission("insights:read");
  const canRank = usePermission("analytics:read");
  const visible = VIEWS.filter((view) => (view === "best" ? canRank : canReadInsights));
  const requested = table.get("view") as View | null;
  const view = visible.find((item) => item === requested) ?? visible[0] ?? "best";

  const summary = useQuery({
    queryKey: queryKeys.intelligence.summary,
    enabled: canReadInsights,
    queryFn: () => unwrap(api.GET("/api/v1/intelligence/summary")),
  });
  const insights = useQuery({
    queryKey: queryKeys.intelligence.insights({ live: true }),
    enabled: canReadInsights,
    queryFn: () => unwrap(api.GET("/api/v1/insights", { params: { query: { page_size: 100 } } })),
  });

  if (summary.data && !summary.data.enabled) {
    return (
      <EmptyState
        icon={PowerOff}
        title={labels.insights.disabledTitle}
        description={labels.insights.disabledBody}
        action={
          <Can permission="company:update">
            <Link href="/settings" className="font-semibold underline">
              {labels.insights.openSettings}
            </Link>
          </Can>
        }
      />
    );
  }

  const advice = (insights.data?.items ?? []).filter(
    (item) => item.insight_type !== "insufficient_history",
  );

  return (
    <div className="mx-auto flex max-w-page flex-col gap-5">
      <div>
        <h1 className="text-titre-page leading-[1.45] tracking-[-0.01em]">{t.title}</h1>
        <p className="text-lg text-muted-foreground">
          {computedText(summary.data?.computed_at ?? null, timeZone)}
        </p>
      </div>

      <div role="group" aria-label={t.viewsLabel} className="flex flex-wrap gap-2.5">
        {visible.map((item) => (
          <button
            key={item}
            type="button"
            aria-pressed={view === item}
            onClick={() => table.replaceAll(item === "advice" ? {} : { view: item })}
            className={cn(
              "min-h-[60px] flex-[1_1_200px] rounded-bouton border-2 px-4 text-lg font-bold outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
              view === item
                ? "border-conseils bg-conseils text-primary-foreground"
                : "border-input bg-card hover:bg-voile",
            )}
          >
            {item === "advice"
              ? t.views.advice(advice.length)
              : item === "best"
                ? t.views.best
                : t.views.forecasts}
          </button>
        ))}
      </div>

      {view === "advice" &&
        (insights.isError ? (
          <ErrorState error={insights.error} onRetry={() => void insights.refetch()} />
        ) : !insights.data ? (
          <Skeleton className="h-96 w-full rounded-carte" />
        ) : (
          <AdviceList items={advice} insufficient={summary.data?.insufficient_data_products ?? 0} />
        ))}
      {view === "best" && <BestArticles />}
      {view === "forecasts" && <NextWeek />}
    </div>
  );
}

/** « Calculés cette nuit à partir de vos ventes », ou le moment du dernier calcul. */
function computedText(computedAt: string | null, timeZone: string): string {
  if (!computedAt) return t.computed.never;
  const today = todayIn(timeZone);
  const day = todayIn(timeZone, new Date(computedAt));
  const time = formatClock(computedAt, timeZone);
  if (day === today) {
    const hour = Number(time.split(" ")[0]);
    return hour < 7 ? t.computed.night : t.computed.today(time);
  }
  if (day === addDays(today, -1)) return t.computed.yesterday(time);
  return t.computed.on(formatDayMonth(day));
}

type Look = {
  icon: LucideIcon;
  tone: string;
  action: string;
  href: (insight: Insight) => string;
};

const article = (insight: Insight) =>
  insight.entity_id ? `/products/${insight.entity_id}` : "/products";

/** Couleur, icône et action directe de chaque type de conseil (maquette 22). */
const LOOKS: Record<InsightType, Look> = {
  stockout_risk: {
    icon: AlertTriangle,
    tone: "bg-stock",
    action: t.actions.order,
    href: (insight) =>
      withFrom(
        insight.entity_id
          ? `/inventory/receive?product=${insight.entity_id}`
          : "/inventory/receive",
        "/insights",
      ),
  },
  debt_overdue: {
    icon: Clock,
    tone: "bg-clients",
    action: t.actions.remind,
    href: (insight) => (insight.entity_id ? `/customers/${insight.entity_id}` : "/customers"),
  },
  expense_anomaly: {
    icon: Zap,
    tone: "bg-depenses",
    action: t.actions.expenses,
    href: () => withFrom("/finance/expenses", "/insights"),
  },
  demand_spike: { icon: TrendingUp, tone: "bg-conseils", action: t.actions.article, href: article },
  slow_mover: { icon: Tag, tone: "bg-ventes", action: t.actions.price, href: article },
  margin_drop: { icon: TrendingDown, tone: "bg-depenses", action: t.actions.price, href: article },
  cash_shortfall: {
    icon: Wallet,
    tone: "bg-argent",
    action: t.actions.money,
    href: () => "/finance",
  },
  cashier_anomaly: {
    icon: Wallet,
    tone: "bg-argent",
    action: t.actions.cash,
    href: () => withFrom("/finance/cash", "/insights"),
  },
  insufficient_history: { icon: Clock, tone: "bg-muted", action: "", href: () => "/insights" },
};

function AdviceList({ items, insufficient }: { items: Insight[]; insufficient: number }) {
  const [explained, setExplained] = useState<Insight | null>(null);
  return (
    <>
      {items.length === 0 ? (
        <p className="rounded-carte border border-border bg-card p-carte text-lg">{t.noAdvice}</p>
      ) : (
        <ul className="flex flex-col gap-3">
          {items.map((item) => (
            <AdviceCard key={item.id} insight={item} onExplain={() => setExplained(item)} />
          ))}
        </ul>
      )}
      {insufficient > 0 && <p className="text-muted-foreground">{t.insufficient(insufficient)}</p>}
      <InsightSheet insight={explained} onOpenChange={(open) => !open && setExplained(null)} />
    </>
  );
}

function AdviceCard({ insight, onExplain }: { insight: Insight; onExplain: () => void }) {
  const queryClient = useQueryClient();
  const canUpdate = usePermission("insights:update");
  const [closed, setClosed] = useState<"resolved" | "dismissed" | null>(null);
  const look = LOOKS[insight.insight_type];
  const close = useMutation({
    mutationFn: (status: "resolved" | "dismissed") =>
      unwrap(
        api.PATCH("/api/v1/insights/{insight_id}", {
          params: { path: { insight_id: insight.id } },
          body: { status },
        }),
      ),
    onSuccess: (_data, status) => {
      setClosed(status);
      void queryClient.invalidateQueries({ queryKey: queryKeys.intelligence.summary });
    },
  });
  const OUTLINE =
    "min-h-[50px] rounded-champ border-2 border-input bg-card px-[18px] font-bold outline-none hover:bg-voile focus-visible:ring-3 focus-visible:ring-ring/50";
  return (
    <li
      className={cn(
        "flex gap-4 rounded-[20px] border border-border bg-card p-[18px]",
        closed && "opacity-60",
      )}
    >
      <span
        aria-hidden
        className={cn(
          "flex size-12 shrink-0 items-center justify-center rounded-champ text-primary-foreground",
          look.tone,
        )}
      >
        <look.icon className="size-6" />
      </span>
      <div className="min-w-0 flex-1 space-y-2">
        <p className="text-[19px] font-bold">{insight.title}</p>
        {insight.body && <p className="text-[17px] text-encre-2">{insight.body}</p>}
        {closed ? (
          <p className="font-bold">{closed === "resolved" ? t.doneThanks : t.ignored}</p>
        ) : (
          <div className="flex flex-wrap gap-2.5">
            <Link
              href={look.href(insight)}
              className={cn(
                "inline-flex min-h-[50px] items-center rounded-champ px-[18px] font-bold text-primary-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                look.tone,
              )}
            >
              {look.action}
            </Link>
            {canUpdate && (
              <>
                <button
                  type="button"
                  disabled={close.isPending}
                  onClick={() => close.mutate("resolved")}
                  className={OUTLINE}
                >
                  {t.done}
                </button>
                <button
                  type="button"
                  disabled={close.isPending}
                  onClick={() => close.mutate("dismissed")}
                  className={OUTLINE}
                >
                  {t.ignore}
                </button>
              </>
            )}
            <button
              type="button"
              onClick={onExplain}
              className="min-h-[50px] px-2 font-semibold text-muted-foreground underline-offset-4 hover:underline"
            >
              {t.why}
            </button>
          </div>
        )}
      </div>
    </li>
  );
}

type RankMetric = "margin" | "quantity" | "revenue" | "days_since_last_sale";
const RANKS: readonly RankMetric[] = ["margin", "quantity", "revenue", "days_since_last_sale"];

/** Poids d'une barre : la partie entière de la valeur, pour la largeur seulement. */
function weight(value: string): number {
  return Math.max(0, Number(value.split(".")[0] ?? "0"));
}

function BestArticles() {
  const { currency, timeZone } = useCompanyLocale();
  const [metric, setMetric] = useState<RankMetric>("margin");
  const today = todayIn(timeZone);
  const params = { metric, from: `${today.slice(0, 8)}01`, to: today, limit: 5 };
  const ranking = useQuery({
    queryKey: queryKeys.analytics.products(params),
    queryFn: () => unwrap(api.GET("/api/v1/analytics/products", { params: { query: params } })),
  });
  const items = ranking.data?.items ?? [];
  const top = Math.max(...items.map((item) => weight(item.value)), 1);
  const display = (value: string) =>
    metric === "quantity"
      ? t.best.sold(formatQty(value))
      : metric === "days_since_last_sale"
        ? t.best.days(Number(value))
        : formatAmount(value, currency);

  return (
    <KitCard>
      <div role="group" aria-label={t.views.best} className="mb-5 flex flex-wrap gap-2">
        {RANKS.map((item) => (
          <Chip
            key={item}
            rubrique="conseils"
            selected={metric === item}
            onClick={() => setMetric(item)}
          >
            {t.best.chips[item]}
          </Chip>
        ))}
      </div>
      <h2 className="mb-4 text-titre-carte">
        {t.best.titles[metric]}{" "}
        <span className="font-normal text-muted-foreground">
          {metric === "days_since_last_sale" ? t.best.today : t.best.thisMonth}
        </span>
      </h2>
      {ranking.isError ? (
        <ErrorState error={ranking.error} onRetry={() => void ranking.refetch()} />
      ) : !ranking.data ? (
        <Skeleton className="h-64 w-full" />
      ) : items.length === 0 ? (
        <p className="text-muted-foreground">
          {metric === "days_since_last_sale" ? t.best.emptyRare : t.best.empty}
        </p>
      ) : (
        <ol className="flex flex-col gap-4">
          {items.map((item, index) => (
            <li key={item.product_id} className="flex items-start gap-3.5">
              <span
                aria-hidden
                className="flex size-8 shrink-0 items-center justify-center rounded-full bg-conseils-teinte font-bold text-conseils-encre"
              >
                {index + 1}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline justify-between gap-3">
                  <Link
                    href={`/products/${item.product_id}`}
                    className="min-h-11 truncate font-bold hover:underline pointer-coarse:min-h-12"
                  >
                    {item.product_name}
                  </Link>
                  <span className="shrink-0 font-bold numeric">{display(item.value)}</span>
                </div>
                <div aria-hidden className="mt-1 h-3 rounded-full bg-conseils-teinte">
                  <div
                    className="h-3 rounded-full bg-conseils"
                    style={{ width: `${Math.max(2, (weight(item.value) / top) * 100)}%` }}
                  />
                </div>
              </div>
            </li>
          ))}
        </ol>
      )}
    </KitCard>
  );
}

function NextWeek() {
  const { timeZone } = useCompanyLocale();
  const forecast = useQuery({
    queryKey: queryKeys.intelligence.forecasts({ nextWeek: true }),
    queryFn: () => unwrap(api.GET("/api/v1/analytics/next-week")),
  });
  if (forecast.isError) {
    return <ErrorState error={forecast.error} onRetry={() => void forecast.refetch()} />;
  }
  if (!forecast.data) return <Skeleton className="h-80 w-full rounded-carte" />;
  const data: Schemas["NextWeekForecast"] = forecast.data;
  const model = modelLabel(data.model_name, data.model_version);
  return (
    <KitCard title={t.forecasts.title}>
      {data.items.length === 0 ? (
        <p className="text-muted-foreground">{t.forecasts.none}</p>
      ) : (
        <ul className="grid grid-cols-[repeat(auto-fill,minmax(250px,1fr))] gap-3">
          {data.items.map((item) => {
            const left = qtyWithUnit(item.on_hand, item.unit);
            return (
              <li
                key={item.product_id}
                className={cn(
                  "space-y-1 rounded-champ p-4",
                  item.low ? "bg-stock-teinte" : "bg-voile",
                )}
              >
                <p className="font-bold">{item.product_name}</p>
                <p className="text-[26px] leading-tight font-extrabold numeric">
                  {qtyWithUnit(item.expected, item.unit)}
                </p>
                {item.lower !== null && item.upper !== null && (
                  <p className="numeric text-muted-foreground">
                    {t.forecasts.range(formatQty(item.lower), formatQty(item.upper))}
                  </p>
                )}
                <p className={cn("font-bold", item.low ? "text-stock-encre" : "text-marque")}>
                  {item.low ? t.forecasts.low(left) : t.forecasts.enough(formatQty(item.on_hand))}
                </p>
              </li>
            );
          })}
        </ul>
      )}
      {data.insufficient_count > 0 && (
        <p className="mt-4 text-muted-foreground">
          {t.forecasts.insufficient(data.insufficient_count)}
        </p>
      )}
      {data.computed_at && model && (
        <p className="mt-2 text-sm text-muted-foreground">
          {t.forecasts.model(formatDate(data.computed_at, timeZone), model)}
        </p>
      )}
    </KitCard>
  );
}
