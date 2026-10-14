import { cn } from "@/lib/utils";

export type MoneyBarGroup = {
  /** Mot sous la paire de barres (« Matin », « Mer », « Semaine 2 »). */
  label: string;
  /** Valeurs déjà formatées, sans unité (« 520 000 »). */
  inDisplay: string;
  outDisplay: string;
  /** Hauteurs relatives : des nombres de **position**, jamais relus comme montants. */
  inWeight: number;
  outWeight: number;
};

/** Hauteur d'une barre : la plus haute vaut `scale`, une valeur non nulle garde 4 px. */
export function barHeight(weight: number, max: number, scale: number): number {
  if (weight <= 0) return 0;
  return Math.max(4, Math.round((weight / Math.max(max, 1)) * scale));
}

/**
 * Barres groupées de la maquette 17 : entré en vert, sorti en orange, la valeur écrite
 * au-dessus de chaque barre, le mot sous chaque paire. Échelle commune ; une valeur non
 * nulle garde 4 px pour qu'une valeur extrême n'écrase pas les autres. Une liste pour les
 * lecteurs d'écran (« Matin : entré 32 500, sorti 35 000 »).
 */
export function MoneyBars({
  groups,
  label,
  inLabel,
  outLabel,
  height = 260,
  scale = 200,
}: {
  groups: readonly MoneyBarGroup[];
  label: string;
  inLabel: string;
  outLabel: string;
  height?: number;
  scale?: number;
}) {
  const max = Math.max(...groups.flatMap((group) => [group.inWeight, group.outWeight]), 1);
  const bar = (weight: number, display: string, tone: "in" | "out", name: string) => (
    <span className="flex h-full max-w-14 min-w-0 flex-1 flex-col items-center justify-end gap-1.5">
      <span
        className={cn(
          "text-[13px] font-bold numeric whitespace-nowrap",
          tone === "in" ? "text-marque" : "text-stock-encre",
        )}
      >
        <span className="sr-only">{name} </span>
        {display}
      </span>
      <span
        aria-hidden
        className={cn(
          "w-full rounded-t-[10px] rounded-b-[3px]",
          tone === "in" ? "bg-primary" : "bg-barre-sortie",
        )}
        style={{ height: barHeight(weight, max, scale) }}
      />
    </span>
  );
  return (
    <div>
      <ul
        aria-label={label}
        className="flex items-end gap-2 border-b-2 border-border sm:gap-4"
        style={{ height }}
      >
        {groups.map((group) => (
          <li key={group.label} className="flex h-full min-w-0 flex-1 justify-center gap-1.5">
            <span className="sr-only">{group.label} : </span>
            {bar(group.inWeight, group.inDisplay, "in", inLabel)}
            {bar(group.outWeight, group.outDisplay, "out", outLabel)}
          </li>
        ))}
      </ul>
      <div aria-hidden className="mt-2.5 flex gap-2 sm:gap-4">
        {groups.map((group) => (
          <span
            key={group.label}
            className="min-w-0 flex-1 text-center leading-tight font-semibold break-words text-encre-2"
          >
            {group.label}
          </span>
        ))}
      </div>
    </div>
  );
}
