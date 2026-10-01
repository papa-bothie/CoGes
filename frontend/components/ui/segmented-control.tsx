"use client";

import { useRef, type KeyboardEvent, type ReactNode } from "react";

import { cn } from "@/lib/utils";

export type SegmentedOption<T extends string> = { value: T; label: ReactNode };

/**
 * Choix exclusif entre quelques valeurs (mode de règlement, sens d'un mouvement, format du
 * reçu, filtre « Toutes / Non lues ») : un groupe de boutons radio, **pas** des onglets, car rien
 * ne s'y rattache comme un panneau. Clavier du rôle `radiogroup` : un seul arrêt de
 * tabulation, flèches pour changer, Début / Fin pour les extrémités.
 */
export function SegmentedControl<T extends string>({
  value,
  onValueChange,
  options,
  className,
  itemClassName,
  ...labelling
}: {
  value: T;
  onValueChange: (value: T) => void;
  options: readonly SegmentedOption<T>[];
  className?: string;
  itemClassName?: string;
} & ({ "aria-label": string } | { "aria-labelledby": string })) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);

  const select = (index: number) => {
    const option = options[(index + options.length) % options.length];
    if (!option) return;
    onValueChange(option.value);
    refs.current[options.indexOf(option)]?.focus();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const moves: Record<string, number> = {
      ArrowRight: index + 1,
      ArrowDown: index + 1,
      ArrowLeft: index - 1,
      ArrowUp: index - 1,
      Home: 0,
      End: options.length - 1,
    };
    const target = moves[event.key];
    if (target === undefined) return;
    event.preventDefault();
    select(target);
  };

  // Une valeur hors liste ne doit pas rendre le groupe inaccessible au clavier.
  const focusable = Math.max(
    0,
    options.findIndex((option) => option.value === value),
  );

  return (
    <div
      role="radiogroup"
      {...labelling}
      className={cn(
        "inline-grid auto-cols-fr grid-flow-col gap-1 rounded-lg bg-muted p-1",
        className,
      )}
    >
      {options.map((option, index) => {
        const checked = option.value === value;
        return (
          <button
            key={option.value}
            ref={(element) => {
              refs.current[index] = element;
            }}
            type="button"
            role="radio"
            aria-checked={checked}
            tabIndex={index === focusable ? 0 : -1}
            onClick={() => onValueChange(option.value)}
            onKeyDown={(event) => onKeyDown(event, index)}
            className={cn(
              "rounded-md px-3 py-1 text-sm font-medium whitespace-nowrap transition-colors outline-none focus-visible:ring-3 focus-visible:ring-ring/50 pointer-coarse:min-h-11",
              checked
                ? "bg-card text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
              itemClassName,
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
