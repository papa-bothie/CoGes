"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { useMe } from "@/hooks/use-me";
import { labels } from "@/lib/labels";
import { can, type PermissionRule } from "@/lib/permissions";
import { cn } from "@/lib/utils";

const t = labels.settingsScreens;

/** Les cinq rubriques ; chacune n'apparaît qu'avec son droit de lecture (le serveur revérifie). */
export const SECTIONS = [
  { href: "/settings", label: t.nav.shop, permission: "company:read" },
  { href: "/settings/people", label: t.nav.people, permission: "users:read" },
  { href: "/settings/rights", label: t.nav.rights, permission: "roles:read" },
  { href: "/settings/history", label: t.nav.history, permission: "audit:read" },
  {
    href: "/settings/files",
    label: t.nav.files,
    permission: { anyOf: ["importexport:export", "importexport:create"] },
  },
] as const satisfies readonly { href: string; label: string; permission: PermissionRule }[];

export function SettingsFrame({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { data: me } = useMe();
  const visible = SECTIONS.filter((section) => can(me?.permissions, section.permission));
  const current = SECTIONS.find((section) => section.href === pathname);
  // Le serveur refuserait (403) : on le dit en une phrase plutôt qu'en erreur.
  const allowed = !me || !current || can(me.permissions, current.permission);
  return (
    <div className="mx-auto flex max-w-page flex-col gap-5">
      <h1 className="text-titre-page leading-[1.45] tracking-[-0.01em]">{t.title}</h1>
      <div className="flex flex-wrap items-start gap-5">
        <nav
          aria-label={t.sections}
          className="flex flex-[1_1_240px] flex-col gap-1 rounded-carte border border-border bg-card p-2.5"
        >
          {visible.map((section) => {
            const here = pathname === section.href;
            return (
              <Link
                key={section.href}
                href={section.href}
                aria-current={here ? "page" : undefined}
                className={cn(
                  "flex min-h-14 items-center rounded-champ px-4 text-libelle outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                  here ? "bg-foreground text-background" : "text-encre-2 hover:bg-voile",
                )}
              >
                {section.label}
              </Link>
            );
          })}
        </nav>
        <section className="flex min-w-0 flex-[4_1_560px] flex-col gap-4 rounded-carte border border-border bg-card p-carte">
          {allowed ? children : <p className="text-muted-foreground">{t.noAccess}</p>}
        </section>
      </div>
    </div>
  );
}
