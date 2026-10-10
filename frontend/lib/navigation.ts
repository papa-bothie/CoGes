import {
  CreditCard,
  House,
  Lightbulb,
  Package,
  ShoppingCart,
  Users,
  type LucideIcon,
} from "lucide-react";

import type { Rubrique } from "@/components/kit/rubrique";
import { labels } from "@/lib/labels";
import type { PermissionRule } from "@/lib/permissions";

export type NavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Couleur de l'onglet actif (maquette v2). */
  rubrique: Rubrique;
  /** Préfixes de chemins qui allument l'entrée : une rubrique couvre plusieurs pages. */
  matches: readonly string[];
  /** Droit qui rend l'entrée utile ; absente = visible par tous. */
  permission?: PermissionRule;
};

/**
 * Les cinq entrées de la maquette v2 (écran 01), dans son ordre, plus « Conseils » à droite.
 *
 * Les droits choisissent les entrées du vendeur : Accueil, Vendre et Clients seulement
 * (prompt de phase 15). Il lit les articles et la caisse pour vendre, mais ne gère ni le
 * stock (`products:create`) ni l'argent (`debts:read`, `expenses:read`).
 *
 * Stock s'allume aussi sur `/inventory` : correction, livraison et « Tous les mouvements »
 * (ADR 0071). Liens provisoires (ADR 0070) : Clients sur `/suppliers`, Conseils sur
 * `/analytics`, jusqu'à la fusion de ces pages aux lots 3c et 3e.
 */
export const MAIN_NAV: readonly NavItem[] = [
  {
    href: "/dashboard",
    label: labels.kit.nav.home,
    icon: House,
    rubrique: "ventes",
    matches: ["/dashboard"],
    permission: "dashboard:read",
  },
  {
    href: "/sales/new",
    label: labels.kit.nav.sell,
    icon: ShoppingCart,
    rubrique: "ventes",
    matches: ["/sales"],
    permission: { anyOf: ["sales:create", "sales:read"] },
  },
  {
    href: "/products",
    label: labels.kit.nav.stock,
    icon: Package,
    rubrique: "stock",
    matches: ["/products", "/inventory"],
    permission: { anyOf: ["products:create", "analytics:read"] },
  },
  {
    href: "/customers",
    label: labels.kit.nav.clients,
    icon: Users,
    rubrique: "clients",
    matches: ["/customers", "/suppliers"],
    permission: "customers:read",
  },
  {
    href: "/finance",
    label: labels.kit.nav.money,
    icon: CreditCard,
    rubrique: "argent",
    matches: ["/finance"],
    permission: { anyOf: ["debts:read", "expenses:read"] },
  },
];

export const ADVICE_NAV: NavItem = {
  href: "/insights",
  label: labels.kit.nav.advice,
  icon: Lightbulb,
  rubrique: "conseils",
  matches: ["/insights", "/analytics"],
  permission: { anyOf: ["insights:read", "analytics:read"] },
};

/** Les réglages, derrière l'engrenage. */
export const SETTINGS_PERMISSION: PermissionRule = {
  anyOf: ["company:read", "users:read", "roles:read", "audit:read"],
};

export function isActive(pathname: string, item: Pick<NavItem, "matches">): boolean {
  return item.matches.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
}
