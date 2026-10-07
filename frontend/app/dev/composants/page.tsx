import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { labels } from "@/lib/labels";

import { Showcase } from "./showcase";

export const metadata: Metadata = { title: labels.kit.showcase.title };

/**
 * Vitrine des composants de la maquette v2 (règle 3 du prompt de phase 15, ADR 0064).
 * Développement seulement, sans connexion (`proxy.ts` la laisse passer) ; en production,
 * elle n'existe pas.
 */
export default function ComponentsPage() {
  if (process.env.NODE_ENV === "production") notFound();
  return <Showcase />;
}
