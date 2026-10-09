"use client";

import { Delete } from "lucide-react";
import { useId, type ReactNode } from "react";

import { labels } from "@/lib/labels";
import { cn } from "@/lib/utils";

import { fieldClasses, RUBRIQUE_CLASSES, type Rubrique } from "./rubrique";

/** Plus long montant tapable : 12 chiffres, la partie entière de `numeric(14,2)` côté serveur. */
const MAX_DIGITS = 12;

/** Ne garde que les chiffres, sans zéro de tête (« 007500 » → « 7500 »). */
export function cleanAmount(raw: string): string {
  const digits = raw.replace(/\D/g, "").replace(/^0+(?=\d)/, "");
  return digits.slice(0, MAX_DIGITS);
}

/**
 * Champ montant de la maquette v2 : 64 px, chiffres en 28 px gras, « F » à droite. Le montant
 * se **tape librement** (règle 3 de la maquette) ; le pavé et les raccourcis n'en sont que des
 * raccourcis. Valeur = chaîne de chiffres entiers (XOF n'a pas de décimales), jamais un `number`.
 */
export function AmountField({
  label,
  value,
  onChange,
  rubrique = "ventes",
  currencyLabel = labels.kit.currencyShort,
  hint,
  invalid = false,
  id,
  autoFocus,
  placeholder,
  hideLabel = false,
  size = "montant",
}: {
  label: ReactNode;
  value: string;
  onChange: (value: string) => void;
  rubrique?: Rubrique;
  currencyLabel?: string;
  hint?: ReactNode;
  invalid?: boolean;
  id?: string;
  autoFocus?: boolean;
  placeholder?: string;
  /** Libellé pour les lecteurs d'écran seulement (« Autre montant donné », maquette 02). */
  hideLabel?: boolean;
  /** `rendu` : le champ « Autre montant » du rendu de monnaie, 56 px et 20 px. */
  size?: "montant" | "rendu";
}) {
  const generated = useId();
  const inputId = id ?? generated;
  const hintId = `${inputId}-aide`;
  return (
    <div className="space-y-2">
      <label htmlFor={inputId} className={hideLabel ? "sr-only" : "block text-libelle"}>
        {label}
      </label>
      <div className="relative">
        <input
          id={inputId}
          inputMode="numeric"
          autoComplete="off"
          autoFocus={autoFocus}
          placeholder={placeholder}
          value={value}
          onChange={(event) => onChange(cleanAmount(event.target.value))}
          aria-invalid={invalid || undefined}
          aria-describedby={hint ? hintId : undefined}
          className={cn(
            fieldClasses(rubrique),
            "pr-12 pl-[18px] font-extrabold numeric placeholder:text-muted-foreground",
            size === "rendu" ? "min-h-14 text-xl" : "min-h-champ-montant text-[28px]",
          )}
        />
        <span
          className={cn(
            "pointer-events-none absolute top-1/2 right-[18px] -translate-y-1/2 font-extrabold text-muted-foreground",
            size === "rendu" ? "text-xl" : "text-[22px]",
          )}
          aria-hidden
        >
          {currencyLabel}
        </span>
      </div>
      {hint && (
        <div id={hintId} className="text-corps">
          {hint}
        </div>
      )}
    </div>
  );
}

const KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "000", "0", "effacer"] as const;

/**
 * Pavé numérique de la maquette v2 (02b) : 1 à 9, « 000 », 0 et effacer, touches de 56 px.
 * Il modifie la même valeur que le champ ; le clavier physique reste utilisable.
 */
export function NumericPad({
  value,
  onChange,
  rubrique = "ventes",
  label = labels.kit.numericPad,
  eraseLabel = labels.kit.eraseDigit,
}: {
  value: string;
  onChange: (value: string) => void;
  rubrique?: Rubrique;
  label?: string;
  eraseLabel?: string;
}) {
  const press = (key: (typeof KEYS)[number]) => {
    if (key === "effacer") onChange(value.slice(0, -1));
    else onChange(cleanAmount(value + key));
  };
  return (
    <div role="group" aria-label={label} className="grid grid-cols-3 gap-2.5">
      {KEYS.map((key) => (
        <button
          key={key}
          type="button"
          onClick={() => press(key)}
          aria-label={key === "effacer" ? eraseLabel : undefined}
          className={cn(
            "flex min-h-touche items-center justify-center rounded-touche border-2 border-input bg-card text-[22px] font-bold text-foreground",
            "outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
            RUBRIQUE_CLASSES[rubrique].pressed,
          )}
        >
          {key === "effacer" ? <Delete className="size-7" aria-hidden /> : key}
        </button>
      ))}
    </div>
  );
}

/** Raccourcis sous le champ (« La moitié : 10 500 F ») : des puces qui posent un montant. */
export function AmountShortcuts({
  shortcuts,
  onPick,
}: {
  shortcuts: readonly { label: string; value: string }[];
  onPick: (value: string) => void;
}) {
  return (
    <div className="grid grid-cols-2 gap-2.5">
      {shortcuts.map((shortcut) => (
        <button
          key={shortcut.label}
          type="button"
          onClick={() => onPick(cleanAmount(shortcut.value))}
          className="min-h-cible rounded-full border-2 border-input bg-card px-4 text-corps font-semibold text-foreground outline-none hover:bg-voile focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          {shortcut.label}
        </button>
      ))}
    </div>
  );
}
