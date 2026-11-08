import type { MetadataRoute } from "next";

import { vitrine } from "@/content/vitrine";

/** La vitrine seule (prompt 37, ADR 0115). */
export const dynamic = "force-static";

export default function sitemap(): MetadataRoute.Sitemap {
  return [{ url: vitrine.siteUrl, changeFrequency: "monthly", priority: 1 }];
}
