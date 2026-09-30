"use client";

import { useMemo } from "react";

import { dayEndIso, dayStartIso } from "@/lib/format/zoned";
import { resolvePeriod, type PeriodPreset } from "@/lib/period";

import { useCompanyLocale } from "./use-me";
import { useTableParams } from "./use-table-params";

/**
 * Période commune aux écrans de pilotage, lue et écrite dans l'URL : un lien partagé ou
 * un rechargement rouvre la même période. `fromIso`/`toIso` bornent les routes qui
 * attendent un instant (paiements) ; `from`/`to` celles qui attendent un jour.
 */
export function usePeriod() {
  const table = useTableParams();
  const { timeZone } = useCompanyLocale();
  const periodParam = table.get("period");
  const fromParam = table.get("from");
  const toParam = table.get("to");

  const period = useMemo(
    () => resolvePeriod({ period: periodParam, from: fromParam, to: toParam }, timeZone),
    [periodParam, fromParam, toParam, timeZone],
  );

  return {
    ...period,
    fromIso: dayStartIso(period.from, timeZone),
    toIso: dayEndIso(period.to, timeZone),
    setPreset: (preset: PeriodPreset) =>
      preset === "custom"
        ? // On part des bornes affichées : une période personnalisée est toujours complète.
          table.update({ period: "custom", from: period.from, to: period.to, page: null })
        : // Un préréglage efface les bornes personnalisées ; la liste repart page 1.
          table.update({
            period: preset === "30d" ? null : preset,
            from: null,
            to: null,
            page: null,
          }),
    setRange: (from: string, to: string) =>
      table.update({ period: "custom", from: from || null, to: to || null, page: null }),
  };
}
