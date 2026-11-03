"use client";

import { useId } from "react";

import { fieldClasses } from "@/components/kit/rubrique";
import { labels } from "@/lib/labels";
import { cn } from "@/lib/utils";

/** Borne de l'API (`products.description`, ADR 0108). */
export const DESCRIPTION_MAX = 500;

/**
 * Description facultative d'un article (ADR 0108) : multiligne, 500 caractères au plus,
 * compteur annoncé aux lecteurs d'écran. Le serveur retire les espaces de bord ; vide = rien.
 */
export function DescriptionField({
  value,
  onChange,
  id,
  className,
  ...rest
}: {
  value: string;
  onChange: (value: string) => void;
  id?: string;
  className?: string;
} & Omit<React.ComponentProps<"textarea">, "value" | "onChange" | "id" | "className">) {
  const generated = useId();
  const fieldId = id ?? generated;
  const t = labels.products.description;
  return (
    <div className={className}>
      <label htmlFor={fieldId} className="mb-2 block text-libelle">
        {t.label}
      </label>
      <textarea
        id={fieldId}
        rows={3}
        maxLength={DESCRIPTION_MAX}
        value={value}
        onChange={(event) => onChange(event.target.value.slice(0, DESCRIPTION_MAX))}
        aria-describedby={`${fieldId}-compte`}
        className={cn(fieldClasses("stock"), "min-h-28 px-4 py-3 text-corps")}
        {...rest}
      />
      <p id={`${fieldId}-compte`} className="mt-1 text-right text-sm text-muted-foreground">
        {t.count(value.length, DESCRIPTION_MAX)}
      </p>
    </div>
  );
}
