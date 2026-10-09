"use client";

import { labels } from "@/lib/labels";
import { cn } from "@/lib/utils";

import { fieldClasses, type Rubrique } from "./rubrique";

/** Quantité tapée : chiffres et une virgule (ou un point), trois décimales au plus. */
export function cleanQuantity(raw: string): string {
  const normalized = raw.replace(".", ",").replace(/[^\d,]/g, "");
  const [integer = "", ...rest] = normalized.split(",");
  const head = integer.replace(/^0+(?=\d)/, "").slice(0, 11);
  return rest.length ? `${head},${rest.join("").slice(0, 3)}` : head;
}

function toNumber(value: string): number {
  return Number(value.replace(",", ".")) || 0;
}

/**
 * Champ quantité de la maquette v2 : « − champ + », boutons de 48 px. La quantité se tape
 * librement ; − et + ne sont que des raccourcis (règle 3). La valeur reste une chaîne
 * décimale à la française (« 2,5 ») ; l'écran la convertit pour l'API.
 */
export function QuantityStepper({
  value,
  onChange,
  itemName,
  min = 0,
  rubrique = "ventes",
  size = "normal",
  inputLabel,
}: {
  value: string;
  onChange: (value: string) => void;
  /** Ce que l'on compte, pour les noms accessibles (« Retirer un Riz brisé 25 kg »). */
  itemName: string;
  min?: number;
  rubrique?: Rubrique;
  size?: "normal" | "grand";
  /** Nom du champ, quand deux compteurs comptent le même article (maquette 09). */
  inputLabel?: string;
}) {
  const current = toNumber(value);
  const step = (delta: number) => {
    const next = Math.max(min, Math.round((current + delta) * 1000) / 1000);
    onChange(String(next).replace(".", ","));
  };
  const button = cn(
    "flex shrink-0 items-center justify-center rounded-touche border-2 border-input bg-card font-bold text-foreground",
    "outline-none hover:bg-voile focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50",
    size === "grand" ? "size-14 text-[26px]" : "size-12 text-[22px]",
  );
  return (
    <div className="flex items-center gap-2.5">
      <button
        type="button"
        className={button}
        onClick={() => step(-1)}
        disabled={current <= min}
        aria-label={labels.kit.decrease(itemName)}
      >
        <span aria-hidden>−</span>
      </button>
      <input
        inputMode="decimal"
        autoComplete="off"
        aria-label={inputLabel ?? `${labels.kit.quantity} : ${itemName}`}
        value={value}
        onChange={(event) => onChange(cleanQuantity(event.target.value))}
        className={cn(
          fieldClasses(rubrique),
          "text-center font-extrabold numeric",
          size === "grand" ? "h-14 w-[100px] text-[26px]" : "h-12 w-14 rounded-mini text-[19px]",
        )}
      />
      <button
        type="button"
        className={button}
        onClick={() => step(1)}
        aria-label={labels.kit.increase(itemName)}
      >
        <span aria-hidden>+</span>
      </button>
    </div>
  );
}
