import type { NextConfig } from "next";

/**
 * Administration de la plateforme (ADR 0089) : application à part, servie par Caddy sur
 * `admin.<domaine>`. Sur le VPS, Caddy envoie `/api/v1/platform/*` à l'API et refuse le
 * reste de `/api/v1` ; cette réécriture sert le développement et les parcours e2e. Le
 * cookie de rafraîchissement de l'administration (`/api/v1/platform/auth`) reste ainsi
 * « first-party ».
 */
function apiOrigin(): string {
  const value = process.env.COGES_API_URL;
  return value ? value.replace(/\/+$/, "") : "http://localhost:8000";
}

const isDev = process.env.NODE_ENV !== "production";

const contentSecurityPolicy = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "font-src 'self'",
  `connect-src 'self'${isDev ? " ws:" : ""}`,
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
].join("; ");

const nextConfig: NextConfig = {
  distDir: process.env.COGES_NEXT_DIST_DIR || ".next",
  output: "standalone",
  poweredByHeader: false,
  devIndicators: false,
  async rewrites() {
    // Seulement l'API de l'administration : aucune route commerçante ne passe par ici.
    return [
      {
        source: "/api/v1/platform/:path*",
        destination: `${apiOrigin()}/api/v1/platform/:path*`,
      },
    ];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Content-Security-Policy", value: contentSecurityPolicy },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "X-Robots-Tag", value: "noindex, nofollow" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
    ];
  },
};

export default nextConfig;
