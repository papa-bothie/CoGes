"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipContentProps,
} from "recharts";

export type CashFlowPoint = {
  /** Jour déjà formaté (« 29/09 »). */
  label: string;
  /** Positions tracées **uniquement** : jamais relues comme montants. */
  inflow: number;
  outflow: number;
  /** Valeurs de l'API, formatées, montrées dans l'info-bulle. */
  inflowDisplay: string;
  outflowDisplay: string;
};

const SERIES = [
  { key: "inflow", color: "hsl(var(--chart-2))" },
  { key: "outflow", color: "hsl(var(--chart-1))" },
] as const;

/**
 * Entrées et sorties de caisse par jour : barres groupées, un seul axe (même unité),
 * légende toujours présente (deux séries), info-bulle au survol avec les deux valeurs
 * exactes. Les couleurs suivent la série, jamais son rang.
 */
export function CashFlowChart({
  data,
  label,
  seriesLabels,
  formatAxis,
  height = 260,
}: {
  data: readonly CashFlowPoint[];
  label: string;
  seriesLabels: { inflow: string; outflow: string };
  formatAxis: (value: number) => string;
  height?: number;
}) {
  return (
    <div className="space-y-3">
      <ul className="flex flex-wrap gap-4 text-sm text-muted-foreground" aria-hidden>
        {SERIES.map((series) => (
          <li key={series.key} className="flex items-center gap-2">
            <span className="size-2.5 rounded-sm" style={{ background: series.color }} />
            {seriesLabels[series.key]}
          </li>
        ))}
      </ul>
      <div role="img" aria-label={label} style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={[...data]}
            margin={{ top: 8, right: 8, bottom: 0, left: 0 }}
            barGap={2}
            barCategoryGap="20%"
          >
            <CartesianGrid vertical={false} stroke="hsl(var(--border))" strokeDasharray="3 3" />
            <XAxis
              dataKey="label"
              tickLine={false}
              axisLine={false}
              tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 12 }}
              minTickGap={24}
            />
            <YAxis
              tickLine={false}
              axisLine={false}
              width={72}
              tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 12 }}
              tickFormatter={formatAxis}
            />
            <Tooltip
              cursor={{ fill: "hsl(var(--muted))", opacity: 0.5 }}
              content={(props: TooltipContentProps) => (
                <FlowTooltip {...props} seriesLabels={seriesLabels} />
              )}
            />
            {SERIES.map((series) => (
              <Bar
                key={series.key}
                dataKey={series.key}
                fill={series.color}
                radius={[4, 4, 0, 0]}
                maxBarSize={18}
                isAnimationActive={false}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function FlowTooltip({
  active,
  payload,
  seriesLabels,
}: TooltipContentProps & { seriesLabels: { inflow: string; outflow: string } }) {
  const point = payload?.[0]?.payload as CashFlowPoint | undefined;
  if (!active || !point) return null;
  return (
    <div className="rounded-md border bg-popover px-3 py-2 text-xs text-popover-foreground shadow-sm">
      <p className="text-muted-foreground">{point.label}</p>
      {SERIES.map((series) => (
        <p key={series.key} className="mt-0.5 flex items-center gap-2">
          <span className="size-2 rounded-sm" style={{ background: series.color }} />
          <span>{seriesLabels[series.key]}</span>
          <span className="ml-auto font-semibold numeric">
            {series.key === "inflow" ? point.inflowDisplay : point.outflowDisplay}
          </span>
        </p>
      ))}
    </div>
  );
}
