import type { NextConfig } from "next";

import pkg from "./package.json" with { type: "json" };

/**
 * L'API est servie **sous la même origine** que le front : `/api/v1/*` est réécrit vers
 * `COGES_API_URL` (ADR 0047). Le cookie de rafraîchissement (`SameSite=Lax`, chemin
 * `/api/v1/auth`, ADR 0006) reste ainsi un cookie « first-party » : deux domaines
 * `*.vercel.app` sont deux sites distincts, et le navigateur ne l'enverrait pas sur un
 * appel direct.
 */
function apiOrigin(): string {
  const value = process.env.COGES_API_URL;
  if (value) return value.replace(/\/+$/, "");
  if (process.env.NODE_ENV === "production" && process.env.VERCEL) {
    throw new Error("COGES_API_URL est obligatoire pour construire le front sur Vercel.");
  }
  return "http://localhost:8000";
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
  poweredByHeader: false,
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
