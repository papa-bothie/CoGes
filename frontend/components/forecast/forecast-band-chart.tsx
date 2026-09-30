"use client";

import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipContentProps,
} from "recharts";

/** Graduation d'axe (repère visuel) : virgule décimale française. */
const axisFormatter = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 1 });

export type ForecastPoint = {
  /** Jour formaté (« 01/10 »). */
  label: string;
  /** Positions tracées uniquement. */
  y: number;
  band: [number, number] | null;
  /** Textes de l'info-bulle, formatés depuis les chaînes de l'API. */
  display: string;
  interval: string | null;
};

/**
 * Prévision jour par jour : ligne de la valeur prévue et **bande d'incertitude** (borne
 * basse – borne haute). Une seule série, donc pas de légende : le titre de la carte la
 * nomme, et l'info-bulle donne valeur et intervalle exacts.
 */
export function ForecastBandChart({
  data,
  label,
  height = 160,
}: {
  data: readonly ForecastPoint[];
  label: string;
  height?: number;
}) {
  return (
    <div role="img" aria-label={label} style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={[...data]} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke="hsl(var(--border))" strokeDasharray="3 3" />
          <XAxis
            dataKey="label"
            tickLine={false}
            axisLine={false}
            tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 11 }}
            minTickGap={16}
          />
          <YAxis
            tickLine={false}
            axisLine={false}
            width={44}
            tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 11 }}
            tickFormatter={(value: number) => axisFormatter.format(value)}
          />
          <Tooltip
            cursor={{ stroke: "hsl(var(--muted-foreground))", strokeWidth: 1 }}
            content={BandTooltip}
          />
          <Area
            dataKey="band"
            stroke="none"
            fill="hsl(var(--chart-1))"
            fillOpacity={0.12}
            isAnimationActive={false}
          />
          <Line
            dataKey="y"
            stroke="hsl(var(--chart-1))"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, strokeWidth: 2, stroke: "hsl(var(--card))" }}
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

function BandTooltip({ active, payload }: TooltipContentProps) {
  const point = payload?.[0]?.payload as ForecastPoint | undefined;
  if (!active || !point) return null;
  return (
    <div className="rounded-md border bg-popover px-3 py-2 text-xs text-popover-foreground shadow-sm">
      <p className="text-muted-foreground">{point.label}</p>
      <p className="mt-0.5 font-semibold numeric">{point.display}</p>
      {point.interval && <p className="numeric text-muted-foreground">{point.interval}</p>}
    </div>
  );
}
