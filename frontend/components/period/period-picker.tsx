"use client";

import { CalendarRange } from "lucide-react";

import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { usePeriod } from "@/hooks/use-period";
import { formatDate } from "@/lib/format";
import { labels } from "@/lib/labels";
import { PERIOD_PRESETS, type PeriodPreset } from "@/lib/period";

/**
 * Sélecteur de période commun (7 j, 30 j, 90 j, mois en cours, personnalisé), gardé dans
 * l'URL. Les bornes résolues sont toujours affichées : on sait sur quels jours portent les
 * chiffres, et dans quel fuseau (celui de l'entreprise).
 */
export function PeriodPicker() {
  const period = usePeriod();
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Select
        value={period.preset}
        onValueChange={(value) => period.setPreset(value as PeriodPreset)}
      >
        <SelectTrigger aria-label={labels.period.label} className="w-48">
          <CalendarRange aria-hidden className="text-muted-foreground" />
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {PERIOD_PRESETS.map((preset) => (
            <SelectItem key={preset} value={preset}>
              {labels.period.presets[preset]}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {period.preset === "custom" ? (
        <>
          <Input
            type="date"
            aria-label={labels.period.from}
            value={period.from}
            max={period.to}
            onChange={(event) => period.setRange(event.target.value, period.to)}
            className="h-9 w-40"
          />
          <Input
            type="date"
            aria-label={labels.period.to}
            value={period.to}
            min={period.from}
            onChange={(event) => period.setRange(period.from, event.target.value)}
            className="h-9 w-40"
          />
        </>
      ) : (
        <span className="text-sm numeric text-muted-foreground">
          {labels.period.range(formatDate(period.from), formatDate(period.to))}
        </span>
      )}
    </div>
  );
}
