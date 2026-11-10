import type { MetadataRoute } from "next";

import { vitrine } from "@/content/vitrine";

/** La vitrine (prompt 37, ADR 0115) et les deux textes légaux (prompt 36, ADR 0117). */
export const dynamic = "force-static";

export default function sitemap(): MetadataRoute.Sitemap {
  return [
    { url: vitrine.siteUrl, changeFrequency: "monthly", priority: 1 },
    { url: `${vitrine.siteUrl}/conditions`, changeFrequency: "yearly", priority: 0.3 },
    { url: `${vitrine.siteUrl}/confidentialite`, changeFrequency: "yearly", priority: 0.3 },
  ];
}
