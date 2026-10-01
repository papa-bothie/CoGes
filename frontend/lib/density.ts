"use client";

import { useCallback, useSyncExternalStore } from "react";

import { DENSITY_KEY } from "./density-boot";

/**
 * Densité des tableaux, réglage **du navigateur** (aucune donnée serveur) : `compact` par
 * défaut, `comfortable` agrandit texte et lignes. L'attribut `data-density` de `<html>` est
 * posé avant l'affichage par `DENSITY_BOOT_SCRIPT`, puis tenu à jour ici.
 */
export type Density = "compact" | "comfortable";

const listeners = new Set<() => void>();

function read(): Density {
  if (typeof document === "undefined") return "compact";
  return document.documentElement.dataset.density === "comfortable" ? "comfortable" : "compact";
}

function apply(density: Density) {
  if (density === "comfortable") document.documentElement.dataset.density = density;
  else delete document.documentElement.dataset.density;
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  // Un autre onglet a changé le réglage.
  const onStorage = (event: StorageEvent) => {
    if (event.key === DENSITY_KEY)
      apply(event.newValue === "comfortable" ? "comfortable" : "compact");
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

export function useDensity(): [Density, (density: Density) => void] {
  const density = useSyncExternalStore(subscribe, read, () => "compact" as const);
  const setDensity = useCallback((next: Density) => {
    try {
      if (next === "comfortable") localStorage.setItem(DENSITY_KEY, next);
      else localStorage.removeItem(DENSITY_KEY);
    } catch {
      // Stockage indisponible (navigation privée…) : le réglage vaut pour la session.
    }
    apply(next);
  }, []);
  return [density, setDensity];
}
