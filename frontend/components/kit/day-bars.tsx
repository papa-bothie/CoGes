import { cn } from "@/lib/utils";

export type DayBar = {
  /** Libellé sous la barre (« Mer », « Aujourd'hui »). */
  label: string;
  /** Valeur affichée au-dessus, déjà formatée (« 62 000 »). */
  display: string;
  /** Hauteur relative : un nombre de **position** (jamais relu comme montant). */
  weight: number;
  current?: boolean;
};

/**
 * Barres de la maquette v2 (01 « Vos ventes des 7 derniers jours ») : une barre par jour,
 * valeur écrite au-dessus, jours passés en vert clair, jour en cours en vert plein et libellé
 * gras ; une ligne de base continue sous les barres. Sept barres de CSS, sans bibliothèque ;
 * une liste pour les lecteurs d'écran (« Mer : 62 000 »).
 *
 * La plus haute barre mesure `scale` px ; une valeur non nulle en garde au moins 4 (prompt
 * de phase 15 : une valeur extrême n'écrase pas les autres).
 */
export function DayBars({
  bars,
  label,
  height = 250,
  scale = 190,
  className,
}: {
  bars: readonly DayBar[];
  /** Nom accessible de la liste (« Ventes des 7 derniers jours »). */
  label: string;
  height?: number;
  scale?: number;
  className?: string;
}) {
  const max = Math.max(...bars.map((bar) => bar.weight), 1);
  const barHeight = (weight: number) =>
    weight > 0 ? Math.max(4, Math.round((weight / max) * scale)) : 0;
  return (
    <div className={className}>
      <ul
        aria-label={label}
        className="flex items-end gap-3 border-b-2 border-border pb-1"
        style={{ height }}
      >
        {bars.map((bar) => (
          <li
            key={bar.label}
            className="flex h-full min-w-0 flex-1 flex-col items-center justify-end gap-1.5"
          >
            <span
              className={cn(
                "text-petit font-bold numeric",
                bar.current ? "text-ventes-encre" : "text-muted-foreground",
              )}
            >
              <span className="sr-only">{bar.label} : </span>
              {bar.display}
            </span>
            <span
              aria-hidden
              className={cn(
                "w-full max-w-16 rounded-t-mini rounded-b-[4px]",
                bar.current ? "bg-ventes" : "bg-barre-claire",
              )}
              style={{ height: barHeight(bar.weight) }}
            />
          </li>
        ))}
      </ul>
      <div aria-hidden className="mt-2 flex gap-3">
        {bars.map((bar) => (
          <span
            key={bar.label}
            className={cn(
              "min-w-0 flex-1 truncate text-center text-sm",
              bar.current
                ? "font-extrabold text-ventes-encre"
                : "font-semibold text-muted-foreground",
            )}
          >
            {bar.label}
          </span>
        ))}
      </div>
    </div>
  );
}
