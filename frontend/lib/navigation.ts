import {
  BarChart3,
  Boxes,
  LayoutDashboard,
  Package,
  Settings,
  ShoppingCart,
  Sparkles,
  Truck,
  Users,
  Wallet,
  type LucideIcon,
} from "lucide-react";

import { labels } from "@/lib/labels";
import type { PermissionRule } from "@/lib/permissions";

export type NavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Droit de lecture qui rend l'entrée utile ; absente = visible par tous. */
  permission?: PermissionRule;
};

/** Ordre du prototype (docs/design/prototype-reference.md § 3). */
export const NAV_ITEMS: readonly NavItem[] = [
  {
    href: "/dashboard",
    label: labels.nav.dashboard,
    icon: LayoutDashboard,
    permission: "dashboard:read",
  },
  { href: "/sales", label: labels.nav.sales, icon: ShoppingCart, permission: "sales:read" },
  { href: "/inventory", label: labels.nav.inventory, icon: Boxes, permission: "inventory:read" },
  { href: "/products", label: labels.nav.products, icon: Package, permission: "products:read" },
  { href: "/customers", label: labels.nav.customers, icon: Users, permission: "customers:read" },
  { href: "/suppliers", label: labels.nav.suppliers, icon: Truck, permission: "suppliers:read" },
  {
    href: "/finance",
    label: labels.nav.finance,
    icon: Wallet,
    permission: { anyOf: ["payments:read", "debts:read", "expenses:read"] },
  },
  {
    href: "/analytics",
    label: labels.nav.analytics,
    icon: BarChart3,
    permission: "analytics:read",
  },
  { href: "/insights", label: labels.nav.insights, icon: Sparkles, permission: "insights:read" },
  {
    href: "/settings",
    label: labels.nav.settings,
    icon: Settings,
    permission: { anyOf: ["company:read", "users:read", "roles:read", "audit:read"] },
  },
];

const EXTRA_TITLES: Record<string, string> = {
  "/notifications": labels.nav.notifications,
};

/** Section d'un chemin (préfixe le plus long) : premier maillon du fil d'Ariane. */
export function pageSection(pathname: string): { label: string; href: string } {
  if (EXTRA_TITLES[pathname]) return { label: EXTRA_TITLES[pathname], href: pathname };
  const match = NAV_ITEMS.filter(
    (item) => pathname === item.href || pathname.startsWith(`${item.href}/`),
  ).sort((a, b) => b.href.length - a.href.length)[0];
  return match ? { label: match.label, href: match.href } : { label: labels.app.name, href: "/" };
}

/** Titre de section affiché dans l'en-tête pour un chemin. */
export function pageTitle(pathname: string): string {
  return pageSection(pathname).label;
}

export function isActive(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}
