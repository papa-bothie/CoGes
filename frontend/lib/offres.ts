/**
 * Offres Pro, Business et Premium (prompt 41, ADR 0132).
 *
 * Les prix et ce que contient chaque offre viennent d'**une seule** source,
 * `content/offres.json`, partagée par la vitrine et « Mon abonnement » ; un test backend
 * (`tests/integration/test_plan_features.py`) la compare aux lignes de `plans`. Aucun montant
 * n'est écrit ailleurs. Le contrôle des droits est fait par le serveur
 * (`plan_feature_required`) : l'écran ne fait que refléter `me.plan.features`.
 */
import data from "@/content/offres.json";
import { vitrine } from "@/content/vitrine";

export type PlanCode = "starter" | "business" | "premium";

export type FeatureCode =
  | "sales"
  | "purchases"
  | "inventory"
  | "dashboard"
  | "reports_exports"
  | "product_photos"
  | "documents"
  | "stock_alerts"
  | "imports"
  | "physical_inventory"
  | "invoice_branding"
  | "stock_locations"
  | "priority_support";

export type Offre = {
  code: PlanCode;
  name: string;
  /** `null` : sur devis (Premium). */
  monthly: number | null;
  annual: number | null;
  maxUsers: number;
  features: FeatureCode[];
};

export const OFFRES = data.plans as Offre[];
export const TRIAL_DAYS: number = data.trialDays;
export const ANNUAL_DISCOUNT_PERCENT: number = data.annualDiscountPercent;

export function offre(code: PlanCode): Offre {
  const found = OFFRES.find((item) => item.code === code);
  if (!found) throw new Error(`offre inconnue : ${code}`);
  return found;
}

export const PRO = offre("starter");
export const BUSINESS = offre("business");
export const PREMIUM = offre("premium");

/** Ce que chaque droit veut dire, en mots simples. Les fonctions des lots E et F sont dites
 * « bientôt » : leur code existe, la fonction pas encore. */
export const FEATURE_LABELS: Record<FeatureCode, string> = {
  sales: "Ventes et caisse",
  purchases: "Livraisons et fournisseurs",
  inventory: "Stock à jour",
  dashboard: "Tableau de bord",
  reports_exports: "Rapports et fichiers Excel ou PDF",
  product_photos: "Photos des articles",
  documents: "Tickets et factures",
  stock_alerts: "Alertes de stock",
  imports: "Ajouter vos articles depuis Excel",
  physical_inventory: "Inventaire du magasin (bientôt)",
  invoice_branding: "Facture à vos couleurs (bientôt)",
  stock_locations: "Dépôt et réserve (bientôt)",
  priority_support: "Support prioritaire",
};

/** Ce qu'ajoute Business à Pro, dans l'ordre du catalogue. */
export const BUSINESS_EXTRAS: FeatureCode[] = BUSINESS.features.filter(
  (code) => !PRO.features.includes(code),
);

/** Droits effectifs de la boutique (`/auth/me`), sans en déduire aucun. */
export function hasFeature(features: readonly string[] | undefined, code: FeatureCode): boolean {
  return features?.includes(code) ?? false;
}

function whatsapp(message: string): string {
  return `https://wa.me/${vitrine.whatsappNumber}?text=${encodeURIComponent(message)}`;
}

/** « Je veux payer CoGes Pro pour 1 mois » (paiement en ligne au lot D). */
export function payLink(name: string, months: 1 | 12): string {
  return whatsapp(`Je veux payer CoGes ${name} pour ${months === 1 ? "1 mois" : "1 an"}.`);
}

export function upgradeLink(): string {
  return whatsapp(`Je veux passer à CoGes ${BUSINESS.name}.`);
}

export function quoteLink(): string {
  return whatsapp(`Bonjour, je voudrais un devis pour CoGes ${PREMIUM.name}.`);
}

/** Le montant d'une offre, en chaîne pour `formatAmount` (jamais de float à l'écran). */
export function amount(value: number): string {
  return String(value);
}
