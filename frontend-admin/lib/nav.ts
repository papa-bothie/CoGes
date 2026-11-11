import {
  BarChart3,
  Building2,
  Inbox,
  History,
  LayoutDashboard,
  ListChecks,
  ServerCog,
  ShieldCheck,
  UserCog,
  Users,
  type LucideIcon,
} from "lucide-react";

export type NavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Profils qui voient le lien ; absent : tous. */
  roles?: string[];
};

export const NAV: { title: string; items: NavItem[] }[] = [
  {
    title: "Accès",
    items: [
      { href: "/", label: "Tableau de bord", icon: LayoutDashboard },
      { href: "/companies", label: "Entreprises", icon: Building2 },
      // Demandes d'inscription (ADR 0118) : le compteur de la file vient de l'en-tête.
      { href: "/demandes", label: "Demandes", icon: Inbox },
      { href: "/users", label: "Utilisateurs", icon: Users },
      { href: "/team", label: "Équipe", icon: UserCog },
      { href: "/audit", label: "Journal", icon: History, roles: ["administrator"] },
      // Double authentification et codes de secours de la personne connectée (ADR 0105).
      { href: "/security", label: "Ma sécurité", icon: ShieldCheck },
    ],
  },
  {
    title: "Plateforme",
    items: [
      { href: "/stats", label: "Statistiques", icon: BarChart3 },
      { href: "/system", label: "Système", icon: ServerCog },
      { href: "/system/jobs", label: "Tâches", icon: ListChecks },
    ],
  },
];

/** Le lien de la page courante : le plus long préfixe (« /system/jobs » avant « /system »). */
export function currentHref(pathname: string, items: NavItem[] = NAV.flatMap((g) => g.items)) {
  const matches = items.filter((item) =>
    item.href === "/"
      ? pathname === "/"
      : pathname === item.href || pathname.startsWith(`${item.href}/`),
  );
  return matches.sort((a, b) => b.href.length - a.href.length)[0]?.href ?? null;
}
