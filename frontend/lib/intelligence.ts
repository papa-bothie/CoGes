/**
 * Présentation des résultats de CoGes Intelligence. Tout est **déjà calculé** par le
 * worker (décision 11) : ici, seulement des libellés et des formats. Une valeur absente
 * se dit « Données insuffisantes », jamais zéro.
 */
import type { Schemas } from "@/lib/api/schema";

import { formatDate, formatMoney, formatQty } from "./format";

export type Insight = Schemas["InsightRead"];
export type InsightType = Schemas["InsightType"];
export type InsightSeverity = Schemas["InsightSeverity"];
export type InsightStatus = Schemas["InsightStatus"];

/** « seasonal_ols v2026-W40 », ou `null` quand l'insight vient d'une règle de gestion. */
export function modelLabel(name: string | null | undefined, version: string | null | undefined) {
  if (!name) return null;
  return version ? `${name} v${version}` : name;
}

/** Valeur d'un insight dans son unité ; `null` ⇒ l'appelant affiche « Données insuffisantes ». */
export function insightValue(
  insight: Pick<Insight, "value" | "unit" | "insufficient_data">,
  currency: string,
): string | null {
  if (insight.insufficient_data || insight.value === null) return null;
  const unit = insight.unit ?? "";
  if (unit === "XOF" || unit === currency) return formatMoney(insight.value, currency);
  if (unit === "%") return `${formatQty(insight.value)} %`;
  return unit ? `${formatQty(insight.value)} ${unit}` : formatQty(insight.value);
}

/** Incertitude lisible : qualificatif et intervalle quand le modèle en produit un. */
export function uncertaintyLabel(
  uncertainty: Schemas["Uncertainty"] | null | undefined,
  unit?: string | null,
): string | null {
  if (!uncertainty) return null;
  const parts: string[] = [];
  if (uncertainty.level) parts.push(uncertainty.level);
  if (uncertainty.lower !== null && uncertainty.lower !== undefined && uncertainty.upper) {
    const suffix = unit ? ` ${unit}` : "";
    parts.push(`${formatQty(uncertainty.lower)} – ${formatQty(uncertainty.upper)}${suffix}`);
  }
  return parts.length > 0 ? parts.join(" · ") : null;
}

/** Clés d'`evidence` déjà montrées ailleurs dans le panneau. */
const HIDDEN_EVIDENCE = new Set([
  "metric_name",
  "unit",
  "value",
  "insufficient_data",
  "thresholds",
]);

const EVIDENCE_LABELS: Record<string, string> = {
  as_of: "Données arrêtées au",
  on_hand: "Stock disponible",
  abc_class: "Classe ABC",
  abc_metric: "Classement ABC selon",
  period_days: "Fenêtre d'observation (jours)",
  days_of_cover: "Couverture du stock (jours)",
  balance: "Solde dû",
  debt_count: "Dettes concernées",
  oldest_due_date: "Plus ancienne échéance",
  sold_days_60d: "Jours de vente sur 60 jours",
  first_sale_day: "Première vente",
  min_cover_days: "Couverture minimale (jours)",
  min_sold_days: "Jours de vente minimum",
  min_history_days: "Historique minimum (jours)",
  sold_days_window: "Fenêtre de comptage (jours)",
  warning_days: "Seuil d'avertissement (jours)",
  critical_days: "Seuil critique (jours)",
};

const MONEY_KEYS = new Set(["balance", "amount", "expected", "observed"]);
const DATE_KEYS = new Set(["as_of", "oldest_due_date", "first_sale_day"]);

function render(key: string, value: unknown, currency: string): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") {
    if (MONEY_KEYS.has(key)) return formatMoney(value, currency);
    if (DATE_KEYS.has(key) || /^\d{4}-\d{2}-\d{2}$/.test(value)) return formatDate(value);
    if (/^-?\d+(\.\d+)?$/.test(value)) return formatQty(value);
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

export type EvidenceFact = { key: string; label: string; value: string };

/** Faits chiffrés de l'`evidence`, lisibles ; les clés inconnues restent affichées. */
export function evidenceFacts(evidence: Record<string, unknown>, currency: string) {
  const facts: EvidenceFact[] = [];
  const thresholds: EvidenceFact[] = [];
  for (const [key, value] of Object.entries(evidence)) {
    if (key === "thresholds" && value && typeof value === "object") {
      for (const [tKey, tValue] of Object.entries(value as Record<string, unknown>)) {
        thresholds.push({
          key: tKey,
          label: EVIDENCE_LABELS[tKey] ?? tKey,
          value: render(tKey, tValue, currency),
        });
      }
      continue;
    }
    if (HIDDEN_EVIDENCE.has(key)) continue;
    facts.push({ key, label: EVIDENCE_LABELS[key] ?? key, value: render(key, value, currency) });
  }
  return { facts, thresholds };
}

/** Types regroupés sous « Anomalies » dans les compteurs de synthèse. */
export const ANOMALY_TYPES: readonly InsightType[] = [
  "expense_anomaly",
  "cashier_anomaly",
  "margin_drop",
  "demand_spike",
];

/** Lien vers l'élément concerné par un insight, quand l'écran existe. */
export function insightHref(insight: Pick<Insight, "entity_table" | "entity_id">): string | null {
  if (!insight.entity_id) return null;
  switch (insight.entity_table) {
    case "products":
      return `/products/${insight.entity_id}`;
    case "customers":
      return `/customers/${insight.entity_id}`;
    case "suppliers":
      return `/suppliers/${insight.entity_id}`;
    case "expenses":
      return "/finance?tab=expenses";
    case "debts":
      return "/finance?tab=debts";
    default:
      return null;
  }
}
