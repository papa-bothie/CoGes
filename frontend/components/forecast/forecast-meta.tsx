import { labels } from "@/lib/labels";

/**
 * Ce que toute recommandation doit afficher (CLAUDE.md § 4, Intelligence) : sa
 * **métrique**, sa date de calcul, le modèle et sa version, son incertitude. Les valeurs
 * arrivent déjà formatées.
 */
export function ForecastMeta({
  metric,
  computedAt,
  model,
  uncertainty,
}: {
  metric: string;
  computedAt: string;
  model: string;
  uncertainty?: string | null;
}) {
  const rows: [string, string][] = [
    [labels.forecast.metric, metric],
    [labels.forecast.computedAt, computedAt],
    [labels.forecast.model, model],
    [labels.forecast.uncertainty, uncertainty ?? labels.forecast.insufficientData],
  ];
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
      {rows.map(([term, value]) => (
        <div key={term} className="contents">
          <dt className="text-muted-foreground">{term}</dt>
          <dd className="numeric">{value}</dd>
        </div>
      ))}
    </dl>
  );
}
