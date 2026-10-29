import type { PermissionRule } from "@/lib/permissions";

/**
 * Registre des écrans (prompt 28, C3, ADR 0099) : pour chaque page de `app/(app)`, le droit
 * exact que son écran exige, celui de la route de l'API qu'il lit ou écrit d'abord. Les
 * entrées du menu, les tuiles du tableau de bord et la garde de page s'y rapportent ; un
 * test échoue si une page n'y figure pas. Le serveur reste l'autorité : ce registre ne
 * fait que refléter ses refus, sans charger de données pour rien.
 *
 * `null` : écran ouvert à toute personne connectée (son compte, ses alertes).
 */
export const ROUTE_ACCESS: Readonly<Record<string, PermissionRule | null>> = {
  "/dashboard": "dashboard:read",
  "/notifications": "notifications:read",
  // « Changer mon mot de passe » (ADR 0098) : à toute personne, depuis le menu du compte.
  "/account/password": null,

  "/sales": "sales:read",
  "/sales/new": "sales:create",
  "/sales/[id]": "sales:read",
  "/sales/[id]/edit": "sales:update",
  "/sales/[id]/receipt": "sales:read",
  "/sales/[id]/returns/new": "sale_returns:create",
  "/sales/returns/[id]": "sale_returns:read",
  "/sales/returns/[id]/receipt": "sale_returns:read",

  "/products": "inventory:read",
  "/products/new": { allOf: ["products:create", "inventory:create"] },
  "/products/categories": "categories:read",
  "/products/[id]": "products:read",
  "/products/[id]/edit": "products:update",
  "/products/[id]/etiquette": "products:read",
  "/inventory": "inventory:read",
  "/inventory/adjust": "inventory:create",
  "/inventory/receive": { allOf: ["inventory:create", "debts:create"] },

  "/customers": "customers:read",
  "/customers/new": "customers:create",
  "/customers/[id]": "customers:read",
  "/customers/[id]/edit": "customers:update",
  "/suppliers": "suppliers:read",
  "/suppliers/new": "suppliers:create",
  "/suppliers/[id]": "suppliers:read",
  "/suppliers/[id]/edit": "suppliers:update",

  "/finance": "analytics:read",
  "/finance/cash": "analytics:read",
  "/finance/collect": { allOf: ["debts:read", "payments:create"] },
  // Payer un fournisseur sort de l'argent : « Gérer… les paiements » (ADR 0103).
  "/finance/pay": { allOf: ["debts:read", "payments:create", "payments:update"] },
  "/finance/debts": "debts:read",
  "/finance/expenses": "expenses:read",
  "/finance/expenses/all": "expenses:read",

  "/insights": "insights:read",
  "/analytics": "insights:read",

  "/settings": "company:read",
  "/settings/people": "users:read",
  "/settings/rights": "roles:read",
  "/settings/history": "audit:read",
  // Un seul écran pour les deux gestes : exporter, et importer des articles (ADR 0099).
  "/settings/files": { anyOf: ["importexport:export", "importexport:create"] },
};

const PATTERNS = Object.keys(ROUTE_ACCESS).map((pattern) => ({
  pattern,
  segments: pattern.split("/").filter(Boolean),
}));

/** Le motif du registre qui décrit ce chemin (`/sales/abc` → `/sales/[id]`), s'il existe. */
export function routePattern(pathname: string): string | undefined {
  const parts = pathname.split("?")[0]!.split("/").filter(Boolean);
  let best: { pattern: string; dynamic: number } | undefined;
  for (const { pattern, segments } of PATTERNS) {
    if (segments.length !== parts.length) continue;
    let dynamic = 0;
    const fits = segments.every((segment, index) => {
      if (segment.startsWith("[")) {
        dynamic += 1;
        return true;
      }
      return segment === parts[index];
    });
    // Un segment écrit en toutes lettres l'emporte sur un paramètre (`/sales/new`).
    if (fits && (!best || dynamic < best.dynamic)) best = { pattern, dynamic };
  }
  return best?.pattern;
}

/**
 * Le droit qu'exige ce chemin : `undefined` si le chemin n'est pas au registre (aucune
 * garde, le serveur tranche), `null` s'il est ouvert à tous.
 */
export function routeRule(pathname: string): PermissionRule | null | undefined {
  const pattern = routePattern(pathname);
  return pattern === undefined ? undefined : ROUTE_ACCESS[pattern];
}
