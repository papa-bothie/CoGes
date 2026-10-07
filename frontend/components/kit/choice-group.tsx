"use client";

import type { LucideIcon } from "lucide-react";
import { RadioGroup } from "radix-ui";

import { cn } from "@/lib/utils";

import { RUBRIQUE_BORDER, RUBRIQUE_CLASSES, type Rubrique } from "./rubrique";

export type Choice<T extends string> = {
  value: T;
  label: string;
  icon?: LucideIcon;
  disabled?: boolean;
};

/**
 * Grand choix exclusif de la maquette v2 (« Tout payé · Une partie · À crédit », sens d'une
 * correction de stock) : grosses cases bordées de 2 px qui se partagent la ligne, la case
 * choisie prend la couleur pleine de la rubrique. Groupe radio (flèches au clavier).
 */
export function ChoiceGroup<T extends string>({
  label,
  value,
  onValueChange,
  choices,
  rubrique = "ventes",
  className,
}: {
  /** Nom accessible du groupe (le libellé visible est posé par l'écran). */
  label: string;
  value: T | undefined;
  onValueChange: (value: T) => void;
  choices: readonly Choice<T>[];
  rubrique?: Rubrique;
  className?: string;
}) {
  return (
    <RadioGroup.Root
      aria-label={label}
      value={value ?? ""}
      onValueChange={(next) => onValueChange(next as T)}
      className={cn("flex flex-wrap gap-2.5", className)}
    >
      {choices.map((choice) => (
        <RadioGroup.Item
          key={choice.value}
          value={choice.value}
          disabled={choice.disabled}
          className={cn(
            "flex min-h-champ-montant flex-[1_1_140px] items-center justify-center gap-3 rounded-bouton border-2 px-3 py-2 text-libelle font-bold transition-colors",
            "outline-none focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50",
            "data-[state=unchecked]:border-input data-[state=unchecked]:bg-card data-[state=unchecked]:text-foreground data-[state=unchecked]:hover:bg-voile",
            choice.value === value &&
              cn(RUBRIQUE_CLASSES[rubrique].solid, RUBRIQUE_BORDER[rubrique]),
          )}
        >
          {choice.icon && <choice.icon className="size-6 shrink-0" aria-hidden />}
          {choice.label}
        </RadioGroup.Item>
      ))}
    </RadioGroup.Root>
  );
}
