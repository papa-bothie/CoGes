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
function apiOrigin(): string {
  const value = process.env.COGES_API_URL;
  return value ? value.replace(/\/+$/, "") : "http://localhost:8000";
}

const isDev = process.env.NODE_ENV !== "production";

// Next injecte des scripts en ligne pour l'hydratation : 'unsafe-inline' reste
// nécessaire sans nonce. Tout le reste est confiné à la même origine.
const contentSecurityPolicy = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self'",
  `connect-src 'self'${isDev ? " ws:" : ""}`,
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
].join("; ");

const nextConfig: NextConfig = {
  // Le front des parcours e2e tourne à côté de celui de développement, dans son propre
  // répertoire de build (deploy/scripts/e2e.sh, ADR 0059). Image Docker et `pnpm dev` : `.next`.
  distDir: process.env.COGES_NEXT_DIST_DIR || ".next",
  // Image Docker du VPS (ADR 0083) : `server.js` et le strict nécessaire de `node_modules`.
  output: "standalone",
  poweredByHeader: false,
  // Le bouton « N » de développement ne doit pas apparaître sur les captures d'écran.
  devIndicators: false,
  env: {
    NEXT_PUBLIC_APP_VERSION: pkg.version,
  },
  async rewrites() {
    return [{ source: "/api/v1/:path*", destination: `${apiOrigin()}/api/v1/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Content-Security-Policy", value: contentSecurityPolicy },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
    ];
  },
};

export default nextConfig;
