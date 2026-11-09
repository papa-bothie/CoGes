import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * Aucune animation sans fin sur la vitrine (prompt 38, ADR 0116 ; WCAG 2.2.2) : toute boucle
 * est finie. On lit les sources de la vitrine : son CSS et ses composants.
 */
const ROOT = join(__dirname, "..", "..");
const FILES = [
  ...readdirSync(join(ROOT, "components", "vitrine"))
    .filter((name) => /\.(css|tsx)$/.test(name))
    .map((name) => join("components", "vitrine", name)),
  join("app", "(vitrine)", "page.tsx"),
];

describe("vitrine : animations finies", () => {
  it("le CSS de la vitrine existe", () => {
    expect(FILES).toContain(join("components", "vitrine", "vitrine.module.css"));
  });

  for (const file of FILES) {
    it(`${file} : aucune animation infinie`, () => {
      const source = readFileSync(join(ROOT, file), "utf8");
      expect(source).not.toMatch(/\binfinite\b/);
      // Les utilitaires Tailwind qui bouclent sans fin.
      expect(source).not.toMatch(/\banimate-(spin|ping|pulse|bounce)\b/);
    });
  }

  it("le CSS de la vitrine ne s'anime que sous prefers-reduced-motion: no-preference", () => {
    const css = readFileSync(join(ROOT, "components", "vitrine", "vitrine.module.css"), "utf8");
    expect(withoutMotionBlocks(css)).not.toMatch(/\b(animation|transition)(-[a-z-]+)?\s*:/);
  });
});

/** Le CSS sans ses blocs `@media (… prefers-reduced-motion: no-preference …) { … }`. */
function withoutMotionBlocks(css: string): string {
  const opening = /@media[^{]*prefers-reduced-motion:\s*no-preference[^{]*\{/g;
  let rest = css.replace(/\/\*[\s\S]*?\*\//g, "");
  for (let match = opening.exec(rest); match; match = opening.exec(rest)) {
    let depth = 1;
    let end = match.index + match[0].length;
    while (depth > 0 && end < rest.length) {
      if (rest[end] === "{") depth += 1;
      if (rest[end] === "}") depth -= 1;
      end += 1;
    }
    rest = rest.slice(0, match.index) + rest.slice(end);
    opening.lastIndex = match.index;
  }
  return rest;
}
