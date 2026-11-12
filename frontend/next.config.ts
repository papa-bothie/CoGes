import type { NextConfig } from "next";

import pkg from "./package.json" with { type: "json" };

/**
 * L'API est servie **sous la même origine** que le front (ADR 0047, ADR 0083) : le
 * navigateur ne voit qu'un domaine. Sur le VPS, Caddy envoie `/api/v1/*` directement à
 * l'API (un saut de moins) ; cette réécriture sert le développement, les parcours e2e et
 * de filet si une requête `/api/v1` atteignait quand même le front. Le cookie de
 * rafraîchissement (`SameSite=Lax`, chemin `/api/v1/auth`, ADR 0006) reste ainsi un cookie
 * « first-party ».
 */
const isDev = process.env.NODE_ENV !== "production";

/**
 * Lue **au build** : Next fige les réécritures dans `routes-manifest.json`. L'image du VPS
 * est construite sans elle (une même image pour la production et la préproduction, qui
 * partagent `coges_edge`) : aucune réécriture, Caddy seul route `/api/v1`, plutôt qu'un
 * filet qui pourrait viser l'API de l'autre pile. En développement : `localhost:8000`.
 */
function apiOrigin(): string | null {
  const value = process.env.COGES_API_URL;
  if (value) return value.replace(/\/+$/, "");
  return isDev ? "http://localhost:8000" : null;
}

// Next injecte des scripts en ligne pour l'hydratation : 'unsafe-inline' reste
// nécessaire sans nonce. Tout le reste est confiné à la même origine.
// 'wasm-unsafe-eval' : le moteur WebAssembly du lecteur de code-barres (iPhone, Firefox ;
// ADR 0106) ne compile pas sans lui ; il n'ouvre ni `eval` ni `new Function`.
function contentSecurityPolicy(imageHosts: string): string {
  return [
    "default-src 'self'",
    `script-src 'self' 'unsafe-inline' ${isDev ? "'unsafe-eval'" : "'wasm-unsafe-eval'"}`,
    "style-src 'self' 'unsafe-inline'",
    `img-src 'self' data: blob:${imageHosts}`,
    "font-src 'self'",
    `connect-src 'self'${isDev ? " ws:" : ""}`,
    // Application installable (ADR 0102) : le worker et le manifeste viennent de la même origine.
    "worker-src 'self'",
    "manifest-src 'self'",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "object-src 'none'",
  ].join("; ");
}

// Photos des articles (ADR 0121) : les images publiques de Cloudinary, et rien d'autre,
// pour l'application. La vitrine et les textes légaux gardent une CSP sans aucun tiers
// (ADR 0115, 0117) : la dernière règle qui pose l'en-tête l'emporte.
const appPolicy = contentSecurityPolicy(" https://res.cloudinary.com");
const publicPolicy = contentSecurityPolicy("");
const PUBLIC_PAGES = ["/", "/conditions", "/confidentialite"];

const nextConfig: NextConfig = {
  // Le front des parcours e2e tourne à côté de celui de développement, dans son propre
  // répertoire de build (deploy/scripts/e2e.sh, ADR 0059). Image Docker et `pnpm dev` : `.next`.
  distDir: process.env.COGES_NEXT_DIST_DIR || ".next",
  // Image Docker du VPS (ADR 0083) : `server.js` et le strict nécessaire de `node_modules`.
  output: "standalone",
  // Étiquette de l'image (ADR 0102) : un écran resté ouvert sur l'ancienne version se recharge
  // au changement d'écran plutôt que de mélanger deux versions. Vide en développement.
  deploymentId: process.env.NEXT_DEPLOYMENT_ID || undefined,
  poweredByHeader: false,
  // Le bouton « N » de développement ne doit pas apparaître sur les captures d'écran.
  devIndicators: false,
  env: {
    NEXT_PUBLIC_APP_VERSION: pkg.version,
  },
  // Anciennes adresses des conditions (prompt 36, ADR 0117) : un seul texte, `/conditions`.
  async redirects() {
    return [
      { source: "/cgu", destination: "/conditions", permanent: true },
      { source: "/cgv", destination: "/conditions", permanent: true },
    ];
  },
  async rewrites() {
    const origin = apiOrigin();
    return origin ? [{ source: "/api/v1/:path*", destination: `${origin}/api/v1/:path*` }] : [];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Content-Security-Policy", value: appPolicy },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          // Caméra pour le scan du code-barres, à la même origine seulement (prompt 33) ; un
          // `camera=()` la refusait avant même de demander à la personne.
          { key: "Permissions-Policy", value: "camera=(self), microphone=(), geolocation=()" },
        ],
      },
      ...PUBLIC_PAGES.map((source) => ({
        source,
        headers: [{ key: "Content-Security-Policy", value: publicPolicy }],
      })),
    ];
  },
};

export default nextConfig;
