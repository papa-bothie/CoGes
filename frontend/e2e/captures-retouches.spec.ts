import { expect, test } from "@playwright/test";

import { DEMO, loginThroughUi } from "./fixtures";
import { SCREENS, settle } from "./screens";

/**
 * Captures avant / après des retouches ciblées (après la phase 14), en clair et en sombre,
 * dans docs/design/captures/retouches/<RETOUCHE>/<CAPTURES_STAGE>/<thème>/. Ne tourne que si
 * les deux variables sont définies ; `RETOUCHE_SCREENS` restreint les écrans (noms de
 * `SCREENS`, séparés par des virgules) :
 *
 *   RETOUCHE=01-barre-laterale RETOUCHE_SCREENS=tableau-de-bord,produits \
 *     CAPTURES_STAGE=avant pnpm e2e captures-retouches
 */
const POINT = process.env.RETOUCHE;
const STAGE = process.env.CAPTURES_STAGE;
const ONLY = process.env.RETOUCHE_SCREENS?.split(",").map((name) => name.trim());

test.describe("captures des retouches", () => {
  test.skip(!POINT || !STAGE, "RETOUCHE ou CAPTURES_STAGE non défini");

  for (const scheme of ["light", "dark"] as const) {
    test.describe(scheme === "light" ? "clair" : "sombre", () => {
      test.use({ colorScheme: scheme });

      test("écrans", async ({ page, request }) => {
        test.setTimeout(180_000);
        await page.goto("/login");
        await loginThroughUi(page, DEMO);
        await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
        for (const screen of SCREENS.filter((item) => !ONLY || ONLY.includes(item.name))) {
          await screen.open(page, request);
          await settle(page);
          // L'indicateur du serveur de développement n'existe pas en production.
          await page.addStyleTag({ content: "nextjs-portal { display: none !important; }" });
          await page.screenshot({
            path: `../docs/design/captures/retouches/${POINT}/${STAGE}/${scheme}/${screen.name}.png`,
            fullPage: true,
            animations: "disabled",
          });
        }
      });
    });
  }
});
