/**
 * Thème de l'administration (prompt 31) : clair par défaut, sombre seulement si la
 * personne l'a choisi. Le réglage du système n'entre pas en compte. Le choix vit dans
 * le navigateur, sous une clé propre à l'administration ; sans stockage, on reste en
 * clair et la bascule marche pour la page en cours.
 */
export type Theme = "light" | "dark";

export const THEME_STORAGE_KEY = "coges-admin:theme";

/**
 * Joué en ligne dans le `<head>` du layout, avant le premier affichage : aucun éclair du
 * mauvais thème. Autorisé par la CSP (`script-src 'self' 'unsafe-inline'`).
 */
export const THEME_BOOT_SCRIPT = `(function(){var t="light";try{if(localStorage.getItem(${JSON.stringify(
  THEME_STORAGE_KEY,
)})==="dark")t="dark"}catch(e){}var r=document.documentElement;r.dataset.theme=t;r.style.colorScheme=t})()`;

export function currentTheme(): Theme {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

const listeners = new Set<() => void>();

export function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  root.dataset.theme = theme;
  root.style.colorScheme = theme;
  listeners.forEach((listener) => listener());
}

/**
 * Abonnement pour `useSyncExternalStore` : la bascule de cette page, et celle d'un onglet
 * voisin (événement `storage`, seulement pour la clé de l'administration).
 */
export function subscribeTheme(listener: () => void): () => void {
  function onStorage(event: StorageEvent) {
    if (event.key === THEME_STORAGE_KEY) applyTheme(event.newValue === "dark" ? "dark" : "light");
  }
  listeners.add(listener);
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

export function saveTheme(theme: Theme): void {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // Navigation privée, stockage bloqué : le choix vaut pour la page en cours.
  }
}
