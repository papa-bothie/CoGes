import type { MetadataRoute } from "next";

import { vitrine } from "@/content/vitrine";

/**
 * Seule la vitrine est indexable (prompt 37, ADR 0115) : `/` exactement et ses images. La
 * connexion et l'application ne le sont pas (elles portent aussi `noindex`). La préproduction
 * est en `noindex` par l'en-tête `X-Robots-Tag` de Caddy.
 */
export const dynamic = "force-static";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: { userAgent: "*", allow: ["/$", "/vitrine/", "/brand/"], disallow: "/" },
    sitemap: `${vitrine.siteUrl}/sitemap.xml`,
    host: vitrine.siteUrl,
  };
}
