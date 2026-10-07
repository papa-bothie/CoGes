"use client";

import { Switch } from "radix-ui";
import { useId, type ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * Interrupteur de la maquette v2 (24 Réglages) : 64 × 36 px, pastille blanche de 28 px,
 * vert d'action quand il est actif. Libellé à gauche, sur une ligne à filet.
 */
export function ToggleSwitch({
  label,
  description,
  checked,
  onCheckedChange,
  disabled,
}: {
  label: ReactNode;
  description?: ReactNode;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <div className="flex items-center justify-between gap-4 border-t border-filet py-3.5">
      <label htmlFor={id} className="min-w-0">
        <span className="block font-bold">{label}</span>
        {description && <span className="block text-sm text-muted-foreground">{description}</span>}
      </label>
      <Switch.Root
        id={id}
        checked={checked}
        onCheckedChange={onCheckedChange}
        disabled={disabled}
        className={cn(
          "relative h-9 w-16 shrink-0 rounded-full transition-colors outline-none",
          "focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50",
          "data-[state=checked]:bg-primary data-[state=unchecked]:bg-input",
        )}
      >
        <Switch.Thumb className="block size-7 translate-x-1 rounded-full bg-blanc shadow-sm transition-transform data-[state=checked]:translate-x-8" />
      </Switch.Root>
    </div>
  );
}
