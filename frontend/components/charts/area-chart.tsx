"use client";

import { useId } from "react";
import {
  Area,
  AreaChart as RechartsAreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipContentProps,
} from "recharts";

export type AreaPoint = {
  /** Libellé de l'axe X, déjà formaté (« 29/09 »). */
  label: string;
  /** Position sur le graphique **uniquement** : jamais réutilisée pour un calcul. */
  y: number;
  /** Valeur affichée dans l'info-bulle, telle que l'API l'a renvoyée puis formatée. */
  display: string;
};

/**
 * Série unique en aire (CA sur 30 jours du prototype) : courbe `chart-1` de 2 px,
 * remplissage en dégradé léger, grille horizontale discrète, réticule + info-bulle au
 * survol. Une seule série : pas de légende, le titre de la carte la nomme.
 */
export function AreaChart({
  data,
  label,
  formatAxis,
  height = 260,
}: {
  data: readonly AreaPoint[];
  label: string;
  formatAxis: (value: number) => string;
  height?: number;
}) {
  const gradientId = useId();
  return (
    <div role="img" aria-label={label} style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <RechartsAreaChart data={[...data]} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="hsl(var(--chart-1))" stopOpacity={0.25} />
              <stop offset="100%" stopColor="hsl(var(--chart-1))" stopOpacity={0.02} />
            </linearGradient>
          </defs>
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
            cursor={{ stroke: "hsl(var(--muted-foreground))", strokeWidth: 1 }}
            content={ChartTooltip}
          />
          <Area
            type="monotone"
            dataKey="y"
            stroke="hsl(var(--chart-1))"
            strokeWidth={2}
            fill={`url(#${gradientId})`}
            activeDot={{ r: 4, strokeWidth: 2, stroke: "hsl(var(--card))" }}
            isAnimationActive={false}
          />
        </RechartsAreaChart>
      </ResponsiveContainer>
    </div>
  );
}

function ChartTooltip({ active, payload }: TooltipContentProps) {
  const point = payload?.[0]?.payload as AreaPoint | undefined;
  if (!active || !point) return null;
  return (
    <div className="rounded-md border bg-popover px-3 py-2 text-xs text-popover-foreground shadow-sm">
      <p className="text-muted-foreground">{point.label}</p>
      <p className="mt-0.5 font-semibold numeric">{point.display}</p>
    </div>
  );
}
