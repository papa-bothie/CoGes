import type { MetadataRoute } from "next";

import { BRAND_COLORS } from "@/lib/brand-colors";

/**
 * Application installable (prompt 29, P2, ADR 0102). `start_url` est l'Accueil, que tout rôle
 * lit (ligne verrouillée de la grille, ADR 0099) : connecté, aucune redirection ; sans session,
 * `proxy.ts` mène à la connexion, comme dans le navigateur.
 */
export default function manifest(): MetadataRoute.Manifest {
  return {
    id: "/",
    name: "CoGes",
    short_name: "CoGes",
    description: "Ventes, stock et argent de votre boutique.",
    lang: "fr",
    dir: "ltr",
    start_url: "/dashboard",
    scope: "/",
    display: "standalone",
    orientation: "any",
    theme_color: BRAND_COLORS.theme,
    background_color: BRAND_COLORS.background,
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icons/maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
