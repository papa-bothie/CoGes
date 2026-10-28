"use client";

import { KeyRound, Lightbulb, LogOut, Moon, Settings, Sun } from "lucide-react";
import Link from "next/link";
import { useTheme } from "next-themes";
import { useState } from "react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { Me } from "@/lib/api/schema";
import { logout, loginUrl } from "@/lib/auth/session";
import { labels } from "@/lib/labels";
import { ADVICE_NAV, resolveNav, SETTINGS_NAV } from "@/lib/navigation";
import { cn } from "@/lib/utils";

function roleLabel(me: Me): string {
  return me.roles.map((role) => role.description ?? role.name).join(", ");
}

/**
 * L'engrenage de la barre du haut (écart à la maquette v2, ADR 0070) : la maquette n'en
 * fait qu'un lien vers les Réglages ; il ouvre ici un menu qui porte aussi le nom de la
 * personne connectée, le mode sombre et la déconnexion, que la barre de la maquette n'a
 * pas. Sur téléphone, « Conseils » y passe aussi : l'en-tête compact (écran 26) n'a que la
 * cloche.
 */
export function SettingsMenu({ me, className }: { me: Me; className?: string }) {
  const { resolvedTheme, setTheme } = useTheme();
  const [leaving, setLeaving] = useState(false);
  const t = labels.shell;
  const dark = resolvedTheme === "dark";
  // Conseils et Réglages s'ouvrent sur un écran que cette personne peut lire (ADR 0099).
  const advice = resolveNav(ADVICE_NAV, me.permissions);
  const settings = resolveNav(SETTINGS_NAV[0]!, me.permissions);

  const handleLogout = async () => {
    setLeaving(true);
    await logout();
    // Rechargement complet : le cache des requêtes et le jeton en mémoire disparaissent.
    window.location.assign(loginUrl("logout"));
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        aria-label={t.settingsMenu}
        className={cn(
          "grid min-h-cible min-w-cible place-items-center rounded-touche text-encre-2 outline-none",
          "hover:bg-voile hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50",
          "aria-expanded:bg-voile aria-expanded:text-foreground",
          className,
        )}
      >
        <Settings className="size-[22px]" aria-hidden />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-64">
        <DropdownMenuLabel className="py-2">
          <span className="block text-corps font-bold text-foreground">{me.user.full_name}</span>
          <span className="block text-sm font-normal text-muted-foreground">{roleLabel(me)}</span>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        {advice && (
          <DropdownMenuItem asChild className="min-h-cible text-corps md:hidden">
            <Link href={advice.href}>
              <Lightbulb aria-hidden /> {advice.label}
            </Link>
          </DropdownMenuItem>
        )}
        {settings && (
          <DropdownMenuItem asChild className="min-h-cible text-corps">
            <Link href={settings.href}>
              <Settings aria-hidden /> {t.settings}
            </Link>
          </DropdownMenuItem>
        )}
        <DropdownMenuItem asChild className="min-h-cible text-corps">
          <Link href="/account/password">
            <KeyRound aria-hidden /> {t.changePassword}
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem
          className="min-h-cible text-corps"
          onSelect={() => setTheme(dark ? "light" : "dark")}
        >
          {dark ? <Sun aria-hidden /> : <Moon aria-hidden />}
          {dark ? labels.kit.theme.toLight : labels.kit.theme.toDark}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          className="min-h-cible text-corps"
          disabled={leaving}
          onSelect={handleLogout}
        >
          <LogOut aria-hidden /> {labels.header.logout}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
