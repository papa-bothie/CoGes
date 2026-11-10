import type { MetadataRoute } from "next";

import { vitrine } from "@/content/vitrine";

/**
 * Seules la vitrine (prompt 37, ADR 0115) et les deux textes légaux (prompt 36, ADR 0117)
 * sont indexables : `/` exactement, ses images, `/conditions` et `/confidentialite`. La
 * connexion et l'application ne le sont pas (elles portent aussi `noindex`). La préproduction
 * est en `noindex` par l'en-tête `X-Robots-Tag` de Caddy.
 */
export const dynamic = "force-static";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: ["/$", "/vitrine/", "/brand/", "/conditions$", "/confidentialite$"],
      disallow: "/",
    },
    sitemap: `${vitrine.siteUrl}/sitemap.xml`,
    host: vitrine.siteUrl,
  };
}
