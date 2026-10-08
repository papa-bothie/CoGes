"use client";

import { useId } from "react";

import { labels } from "@/lib/labels";
import { addDays, todayIn } from "@/lib/period";
import { cn } from "@/lib/utils";

import { Chip } from "./chip";
import { fieldClasses, type Rubrique } from "./rubrique";

export type When = { kind: "today" | "yesterday" | "other"; day: string };

export const TODAY: When = { kind: "today", day: "" };

/** Jour choisi (« 2026-10-05 ») dans le fuseau de l'entreprise. */
export function whenDay(when: When, timeZone: string): string {
  const today = todayIn(timeZone);
  if (when.kind === "today") return today;
  if (when.kind === "yesterday") return addDays(today, -1);
  return when.day || today;
}

/**
 * « Quand ? » de la maquette v2 (dépenses) : Aujourd'hui, Hier, Autre jour. Le jour
 * précis ne se demande que pour « Autre jour », jamais dans le futur.
 */
export function WhenChips({
  value,
  onChange,
  timeZone,
  rubrique = "depenses",
}: {
  value: When;
  onChange: (value: When) => void;
  timeZone: string;
  rubrique?: Rubrique;
}) {
  const labelId = useId();
  const dayId = useId();
  const t = labels.payment;
  return (
    <div className="space-y-2">
      <p id={labelId} className="text-libelle">
        {t.when}
      </p>
      <div role="group" aria-labelledby={labelId} className="flex flex-wrap gap-2.5">
        {(["today", "yesterday", "other"] as const).map((kind) => (
          <Chip
            key={kind}
            rubrique={rubrique}
            selected={value.kind === kind}
            onClick={() =>
              onChange({ kind, day: kind === "other" ? whenDay(value, timeZone) : "" })
            }
          >
            {kind === "today" ? t.today : kind === "yesterday" ? t.yesterday : t.otherDay}
          </Chip>
        ))}
      </div>
      {value.kind === "other" && (
        <div className="space-y-1.5">
          <label htmlFor={dayId} className="block text-petit font-bold">
            {t.otherDayLabel}
          </label>
          <input
            id={dayId}
            type="date"
            value={value.day}
            max={todayIn(timeZone)}
            onChange={(event) => onChange({ kind: "other", day: event.target.value })}
            className={cn(fieldClasses(rubrique), "min-h-cible px-4 text-corps sm:w-60")}
          />
        </div>
      )}
    </div>
  );
}
