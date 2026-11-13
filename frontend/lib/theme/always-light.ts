import type { Viewport } from "next";

import { BRAND_COLORS } from "@/lib/brand-colors";

/**
 * Pages d'entrée toujours claires (prompt 39, bloc C, ADR 0123) : la vitrine, la connexion,
 * l'inscription, la vérification et les deux textes légaux. `providers.tsx` y force le thème
 * clair au niveau de next-themes, sans rien écrire dans le stockage : le choix de la personne
 * (clair, sombre, automatique) revient dès qu'elle quitte ces pages. `/cgu` et `/cgv`
 * redirigent avant tout rendu.
 */
const EXACT = new Set([
  "/",
  "/login",
  "/inscription",
  "/verification",
  "/conditions",
  "/confidentialite",
]);
const TOKEN = /^\/verification\/[^/]+$/;

export function isAlwaysLight(pathname: string | null): boolean {
  if (!pathname) return false;
  return EXACT.has(pathname) || TOKEN.test(pathname);
}

/**
 * `<meta name="color-scheme" content="light">` : formulaires natifs et barre de défilement
 * claires, pas d'inversion par le « sombre forcé » de certains navigateurs mobiles. La barre
 * du navigateur prend le fond papier.
 */
export const ALWAYS_LIGHT_VIEWPORT = {
  colorScheme: "light",
  themeColor: BRAND_COLORS.background,
} satisfies Viewport;
