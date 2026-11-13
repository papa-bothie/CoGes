import { mkdirSync } from "node:fs";

import { test, type Page } from "@playwright/test";

/**
 * Captures avant / après des pages d'entrée (prompt 39, ADR 0123) : la vitrine, la connexion
 * et l'inscription, à 1280 et 360 px, en clair puis avec un appareil en sombre. Ne tourne que
 * si `ENTREE_CAPTURES` nomme un dossier :
 *
 *   ENTREE_CAPTURES=docs/design/captures/prompt-39/apres pnpm exec playwright test captures-entree
 */
const OUT = process.env.ENTREE_CAPTURES;

const PAGES = [
  { name: "vitrine", path: "/" },
  { name: "connexion", path: "/login" },
  { name: "inscription", path: "/inscription" },
] as const;

async function finish(page: Page) {
  await page.evaluate(() => {
    for (const animation of document.getAnimations()) {
      if (animation.timeline === document.timeline) animation.finish();
    }
  });
}

test.describe("captures des pages d'entrée", () => {
  test.skip(!OUT, "ENTREE_CAPTURES non défini");

  for (const scheme of ["light", "dark"] as const) {
    for (const width of [1280, 360] as const) {
      test(`${scheme} ${width} px`, async ({ page }) => {
        mkdirSync(OUT!, { recursive: true });
        await page.emulateMedia({ colorScheme: scheme, reducedMotion: "reduce" });
        await page.setViewportSize({ width, height: width === 360 ? 740 : 800 });
        for (const { name, path } of PAGES) {
          await page.goto(path);
          await page.waitForLoadState("networkidle");
          await finish(page);
          await page.screenshot({
            path: `${OUT}/${name}-${width}-${scheme === "light" ? "clair" : "sombre"}.png`,
            animations: "disabled",
          });
        }
      });
    }
  }
});
