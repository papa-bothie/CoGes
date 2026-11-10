import type { Metadata } from "next";

import { LegalPage } from "@/components/legal/legal-page";
import { legalDocument } from "@/lib/legal/documents";

/** `/confidentialite` (prompt 36, ADR 0117) : statique, publique, indexable. */
export const dynamic = "force-static";

export function generateMetadata(): Metadata {
  const { title } = legalDocument("confidentialite");
  return {
    title: { absolute: `${title} — CoGes` },
    alternates: { canonical: "/confidentialite" },
    robots: { index: true, follow: true },
  };
}

export default function Page() {
  return <LegalPage slug="confidentialite" />;
}
