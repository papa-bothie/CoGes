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
 * gras. Sept barres de CSS, sans bibliothèque ; une liste pour les lecteurs d'écran
 * (« Mer : 62 000 »).
 */
export function DayBars({
  bars,
  label,
  height = 200,
  className,
}: {
  bars: readonly DayBar[];
  /** Nom accessible de la liste (« Ventes des 7 derniers jours »). */
  label: string;
  height?: number;
  className?: string;
}) {
  const max = Math.max(...bars.map((bar) => bar.weight), 1);
  return (
    <ul aria-label={label} className={cn("flex gap-3", className)}>
      {bars.map((bar) => (
        <li key={bar.label} className="flex min-w-0 flex-1 flex-col items-center">
          <span className="flex w-full flex-1 flex-col items-center justify-end gap-2 border-b-2 border-filet">
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
                "w-full max-w-16 rounded-t-mini",
                bar.current ? "bg-ventes" : "bg-barre-claire",
              )}
              style={{ height: Math.max(4, Math.round((bar.weight / max) * height)) }}
            />
          </span>
          <span
            aria-hidden
            className={cn(
              "mt-2.5 w-full truncate text-center text-corps",
              bar.current ? "font-extrabold text-ventes-encre" : "text-muted-foreground",
            )}
          >
            {bar.label}
          </span>
        </li>
      ))}
    </ul>
  );
}
