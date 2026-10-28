import {
  CreditCard,
  House,
  Lightbulb,
  Package,
  Settings,
  ShoppingCart,
  Users,
  type LucideIcon,
} from "lucide-react";

import type { Rubrique } from "@/components/kit/rubrique";
import { labels } from "@/lib/labels";
import { can, type PermissionRule } from "@/lib/permissions";

export type NavTarget = { href: string; permission: PermissionRule | null };

export type NavItem = {
  label: string;
  icon: LucideIcon;
  /** Couleur de l'onglet actif (maquette v2). */
  rubrique: Rubrique;
  /** Préfixes de chemins qui allument l'entrée : une rubrique couvre plusieurs pages. */
  matches: readonly string[];
  /**
   * Les écrans de la rubrique, dans l'ordre de préférence, chacun avec **son** droit
   * (celui du registre `lib/access.ts`, vérifié par un test). L'entrée s'affiche si l'un
   * est permis et s'ouvre sur le premier permis : jamais un écran par un droit voisin
   * (ADR 0099).
   */
  targets: readonly NavTarget[];
};

/** Une entrée prête à afficher : l'écran où elle mène pour cette personne. */
export type ResolvedNavItem = Omit<NavItem, "targets"> & { href: string };

/**
 * Les cinq entrées de la maquette v2 (écran 01), dans son ordre, plus « Conseils » à droite.
 *
 * Chaque entrée suit le droit exact de ses écrans (ADR 0099) : le vendeur, qui lit le
 * stock, voit Stock en lecture ; un comptable à qui le gérant n'a laissé que « Encaisser
 * une dette » voit Argent ouvert sur les dettes, pas sur les comptes qu'il ne lit plus.
 */
export const MAIN_NAV: readonly NavItem[] = [
  {
    label: labels.kit.nav.home,
    icon: House,
    rubrique: "ventes",
    matches: ["/dashboard"],
    targets: [{ href: "/dashboard", permission: "dashboard:read" }],
  },
  {
    label: labels.kit.nav.sell,
    icon: ShoppingCart,
    rubrique: "ventes",
    matches: ["/sales"],
    targets: [
      { href: "/sales/new", permission: "sales:create" },
      { href: "/sales", permission: "sales:read" },
    ],
  },
  {
    label: labels.kit.nav.stock,
    icon: Package,
    rubrique: "stock",
    matches: ["/products", "/inventory"],
    targets: [{ href: "/products", permission: "inventory:read" }],
  },
  {
    label: labels.kit.nav.clients,
    icon: Users,
    rubrique: "clients",
    matches: ["/customers", "/suppliers"],
    targets: [
      { href: "/customers", permission: "customers:read" },
      { href: "/suppliers", permission: "suppliers:read" },
    ],
  },
  {
    label: labels.kit.nav.money,
    icon: CreditCard,
    rubrique: "argent",
    matches: ["/finance"],
    targets: [
      { href: "/finance", permission: "analytics:read" },
      { href: "/finance/debts", permission: "debts:read" },
      { href: "/finance/expenses", permission: "expenses:read" },
    ],
  },
];

export const ADVICE_NAV: NavItem = {
  label: labels.kit.nav.advice,
  icon: Lightbulb,
  rubrique: "conseils",
  matches: ["/insights", "/analytics"],
  targets: [{ href: "/insights", permission: "insights:read" }],
};

/** Les réglages, derrière l'engrenage : chaque page a son droit. */
export const SETTINGS_NAV: readonly NavItem[] = [
  {
    label: labels.shell.settings,
    icon: Settings,
    rubrique: "ventes",
    matches: ["/settings"],
    targets: [
      { href: "/settings", permission: "company:read" },
      { href: "/settings/people", permission: "users:read" },
      { href: "/settings/rights", permission: "roles:read" },
      { href: "/settings/history", permission: "audit:read" },
      {
        href: "/settings/files",
        permission: { anyOf: ["importexport:export", "importexport:create"] },
      },
    ],
  },
];

/** L'entrée telle que cette personne la voit, ou `null` si aucun de ses écrans n'est permis. */
export function resolveNav(
  item: NavItem,
  permissions: readonly string[] | undefined,
): ResolvedNavItem | null {
  const target = item.targets.find(
    (candidate) => candidate.permission === null || can(permissions, candidate.permission),
  );
  if (!target) return null;
  return {
    label: item.label,
    icon: item.icon,
    rubrique: item.rubrique,
    matches: item.matches,
    href: target.href,
  };
}

export function visibleNav(
  items: readonly NavItem[],
  permissions: readonly string[] | undefined,
): ResolvedNavItem[] {
  return items.flatMap((item) => resolveNav(item, permissions) ?? []);
}

export function isActive(pathname: string, item: Pick<NavItem, "matches">): boolean {
  return item.matches.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
}
