"use client";

import type { LucideIcon } from "lucide-react";
import { RadioGroup } from "radix-ui";

import { cn } from "@/lib/utils";

import { RUBRIQUE_CLASSES, type Rubrique } from "./rubrique";

export type TileChoice<T extends string> = { value: T; label: string; icon: LucideIcon };

/**
 * Tuiles de choix avec icône (maquette 10 « Pourquoi ? », 20 catégories de dépense) :
 * grille de cases de 104 px, icône au-dessus du libellé ; la case choisie prend la teinte de
 * la rubrique. Groupe radio.
 */
export function ChoiceTiles<T extends string>({
  label,
  value,
  onValueChange,
  choices,
  rubrique = "stock",
  className,
}: {
  label: string;
  value: T | undefined;
  onValueChange: (value: T) => void;
  choices: readonly TileChoice<T>[];
  rubrique?: Rubrique;
  className?: string;
}) {
  return (
    <RadioGroup.Root
      aria-label={label}
      value={value ?? ""}
      onValueChange={(next) => onValueChange(next as T)}
      className={cn("grid grid-cols-[repeat(auto-fill,minmax(140px,1fr))] gap-2.5", className)}
    >
      {choices.map((choice) => (
        <RadioGroup.Item
          key={choice.value}
          value={choice.value}
          className={cn(
            "flex min-h-[104px] flex-col items-center justify-center gap-2 rounded-bouton border-2 p-2.5 text-center text-corps font-bold transition-colors",
            "outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
            choice.value === value
              ? RUBRIQUE_CLASSES[rubrique].picked
              : "border-input bg-card text-foreground hover:bg-voile",
          )}
        >
          <choice.icon className="size-7" aria-hidden />
          {choice.label}
        </RadioGroup.Item>
      ))}
    </RadioGroup.Root>
  );
}
