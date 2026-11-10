import { readFileSync } from "node:fs";
import path from "node:path";

import { parseLegal, type LegalDocument } from "./parse";

/** Les deux textes déposés par le propriétaire ; jamais rédigés ni modifiés dans le code. */
export const LEGAL_TEXTS = {
  conditions: "conditions.md",
  confidentialite: "confidentialite.md",
} as const;

export type LegalSlug = keyof typeof LEGAL_TEXTS;

/** Lu au build par les pages statiques `/conditions` et `/confidentialite`. */
export function legalDocument(slug: LegalSlug): LegalDocument {
  const file = path.join(process.cwd(), "content", "legal", LEGAL_TEXTS[slug]);
  return parseLegal(readFileSync(file, "utf8"), LEGAL_TEXTS[slug]);
}
