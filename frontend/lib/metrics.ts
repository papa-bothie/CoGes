/**
 * Les huit métriques « valeur produit » du Diagramme 7 : **distinctes, jamais fusionnées**.
 * Chaque classement nomme la sienne ; aucun « meilleur produit », aucun score combiné.
 *
 * Les libellés affichés sur un classement sont ceux **renvoyés par l'API**
 * (`metric_label`) ; ceux d'ici ne servent qu'au sélecteur, avant la réponse, et un test
 * vérifie qu'aucun ne glisse vers une formulation interdite.
 */
import type { Schemas } from "@/lib/api/schema";

import { formatMoney, formatQty } from "./format";
import { decimalParts, groupDigits } from "./format/money";

export type ProductMetric = Schemas["ProductMetric"];

export const METRICS: readonly ProductMetric[] = [
  "revenue",
  "margin",
  "quantity",
  "frequency",
  "rotation",
  "velocity",
  "demand_trend",
  "future_potential",
];

export const METRIC_TEXTS: Record<
  ProductMetric,
  { label: string; definition: string; leader: (product: string) => string }
> = {
  revenue: {
    label: "Chiffre d'affaires généré",
    definition: "Somme des ventes nettes du produit sur la période, retours déduits.",
    leader: (p) => `${p} génère le plus fort chiffre d'affaires sur la période.`,
  },
  margin: {
    label: "Marge générée",
    definition:
      "Chiffre d'affaires net moins le coût d'achat (CMP figé à la vente), sur la période.",
    leader: (p) => `${p} génère la plus forte marge sur la période.`,
  },
  quantity: {
    label: "Quantité vendue",
    definition: "Unités écoulées sur la période, retours déduits.",
    leader: (p) => `${p} est le plus vendu en volume sur la période.`,
  },
  frequency: {
    label: "Fréquence de vente",
    definition: "Nombre de ventes distinctes contenant le produit.",
    leader: (p) => `${p} apparaît dans le plus grand nombre de ventes.`,
  },
  rotation: {
    label: "Rotation du stock",
    definition: "Quantité vendue rapportée au stock moyen détenu sur la période.",
    leader: (p) => `${p} a la plus forte rotation de stock.`,
  },
  velocity: {
    label: "Vélocité des ventes",
    definition: "Unités vendues par jour, sur la période.",
    leader: (p) => `${p} s'écoule le plus rapidement, en unités par jour.`,
  },
  demand_trend: {
    label: "Évolution de la demande",
    definition: "Variation de la vélocité entre la période et la période précédente de même durée.",
    leader: (p) => `La demande de ${p} progresse le plus par rapport à la période précédente.`,
  },
  future_potential: {
    label: "Potentiel futur estimé",
    definition:
      "Ventes prévues par CoGes Intelligence sur l'horizon de prévision, avec leur incertitude.",
    leader: (p) => `${p} est prévu avec les plus fortes ventes sur l'horizon de prévision.`,
  },
};

const UNIT_SUFFIX: Record<string, string> = {
  unité: "u.",
  vente: "ventes",
  fois: "×",
  "unité/jour": "u./jour",
};

/** Valeur d'une métrique dans **son** unité (renvoyée par l'API), sans calcul. */
export function formatMetricValue(
  value: string | null | undefined,
  unit: string,
  currency: string,
  options: { estimate?: boolean } = {},
) {
  if (value === null || value === undefined) return "—";
  if (unit === currency || unit === "XOF") return formatMoney(value, currency);
  if (unit === "%") {
    const parts = decimalParts(value, 1);
    if (!parts) return "—";
    const fraction = parts.fraction.replace(/0+$/, "");
    const sign = parts.negative ? "−" : /^0*$/.test(parts.integer + parts.fraction) ? "" : "+";
    return `${sign}${groupDigits(parts.integer)}${fraction ? `,${fraction}` : ""} %`;
  }
  const suffix = UNIT_SUFFIX[unit] ?? unit;
  if (options.estimate) {
    // Une prévision n'a pas la précision d'une quantité comptée : une décimale suffit.
    const parts = decimalParts(value, 1);
    if (!parts) return "—";
    const fraction = parts.fraction.replace(/0+$/, "");
    return `${parts.negative ? "-" : ""}${groupDigits(parts.integer)}${fraction ? `,${fraction}` : ""} ${suffix}`;
  }
  return `${formatQty(value)} ${suffix}`;
}
