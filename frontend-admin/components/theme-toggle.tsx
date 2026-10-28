"use client";

import { Moon, Sun } from "lucide-react";
import { useSyncExternalStore } from "react";

import { applyTheme, currentTheme, saveTheme, subscribeTheme, type Theme } from "@/lib/theme";

/**
 * Bascule clair / sombre (prompt 31) : deux états, pas de « système ». Le thème est déjà
 * posé par le script du layout ; le bouton le lit, le change et suit l'onglet voisin. Le
 * serveur rend toujours le clair : React reprend la valeur réelle juste après l'hydratation.
 */
export function ThemeToggle({ className = "" }: { className?: string }) {
  const theme = useSyncExternalStore(subscribeTheme, currentTheme, () => "light" as Theme);

  const dark = theme === "dark";
  const label = dark ? "Passer en mode clair" : "Passer en mode sombre";

  function toggle() {
    const next: Theme = dark ? "light" : "dark";
    applyTheme(next);
    saveTheme(next);
  }

  return (
    <button
      type="button"
      onClick={toggle}
      aria-pressed={dark}
      aria-label={label}
      title={label}
      className={`inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg ${className}`}
    >
      {dark ? (
        <Sun aria-hidden="true" className="size-5" />
      ) : (
        <Moon aria-hidden="true" className="size-5" />
      )}
    </button>
  );
}
