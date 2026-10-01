"use client";

import {
  Bar,
  BarChart as RechartsBarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipContentProps,
} from "recharts";

export type PeriodPoint = {
  /** Libellé de l'axe X, déjà formaté (« 29/09 »). */
  label: string;
  /** Position sur le graphique **uniquement** : jamais réutilisée pour un calcul. */
  y: number;
  /** Valeur affichée dans l'info-bulle, telle que l'API l'a renvoyée puis formatée. */
  display: string;
};

/**
 * Série unique en barres (CA par jour, semaine ou mois) : **une barre par période**, car chaque
 * valeur est un total distinct ; une courbe lissée suggérait des valeurs entre deux jours.
 * Barres `chart-1` aux coins hauts arrondis, grille horizontale discrète, info-bulle au
 * survol. Une seule série : pas de légende, le titre de la carte la nomme.
 */
export function PeriodBarChart({
  data,
  label,
  formatAxis,
  height = 260,
}: {
  data: readonly PeriodPoint[];
  label: string;
  formatAxis: (value: number) => string;
  height?: number;
}) {
  return (
    <div role="img" aria-label={label} style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <RechartsBarChart
          data={[...data]}
          margin={{ top: 8, right: 8, bottom: 0, left: 0 }}
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
          <Tooltip cursor={{ fill: "hsl(var(--muted))" }} content={ChartTooltip} />
          <Bar
            dataKey="y"
            fill="hsl(var(--chart-1))"
            radius={[3, 3, 0, 0]}
            maxBarSize={28}
            isAnimationActive={false}
          />
        </RechartsBarChart>
      </ResponsiveContainer>
    </div>
  );
}

function ChartTooltip({ active, payload }: TooltipContentProps) {
  const point = payload?.[0]?.payload as PeriodPoint | undefined;
  if (!active || !point) return null;
  return (
    <div className="rounded-md border bg-popover px-3 py-2 text-xs text-popover-foreground shadow-sm">
      <p className="text-muted-foreground">{point.label}</p>
      <p className="mt-0.5 font-semibold numeric">{point.display}</p>
    </div>
  );
}
