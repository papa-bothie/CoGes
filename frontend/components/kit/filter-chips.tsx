"use client";

import { labels } from "@/lib/labels";

import { Chip } from "./chip";

/** Bouton secondaire de la maquette v2 : bordé, 48 px au moins. */
export const OUTLINE_ACTION =
  "inline-flex min-h-cible items-center justify-center gap-2 rounded-champ border-2 border-input bg-card px-4 font-bold outline-none hover:bg-voile focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50";

/** Une ligne de puces de filtre : la valeur choisie, ou `null` pour « tout ». */
export function FilterChips<T extends string>({
  label,
  value,
  options,
  allLabel,
  onChange,
}: {
  label: string;
  value: T | null;
  options: readonly (readonly [T, string])[];
  allLabel: string;
  onChange: (next: T | null) => void;
}) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap gap-2">
      <Chip selected={value === null} onClick={() => onChange(null)}>
        {allLabel}
      </Chip>
      {options.map(([option, text]) => (
        <Chip key={option} selected={value === option} onClick={() => onChange(option)}>
          {text}
        </Chip>
      ))}
    </div>
  );
}

/** « Voir plus » sous une liste chargée par pages. */
export function MoreButton({ pending, onClick }: { pending: boolean; onClick: () => void }) {
  return (
    <button type="button" disabled={pending} onClick={onClick} className={OUTLINE_ACTION}>
      {labels.kit.more}
    </button>
  );
}
