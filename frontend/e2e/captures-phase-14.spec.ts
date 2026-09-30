import { expect, test } from "@playwright/test";

import { DEMO, loginThroughUi } from "./fixtures";
import { SCREENS, settle } from "./screens";

/**
 * Captures avant / après de la phase 14, en clair et en sombre
 * (docs/design/captures/phase-14/<CAPTURES_STAGE>/). Ne tourne que si `CAPTURES_STAGE` est
 * défini : `CAPTURES_STAGE=avant pnpm e2e captures-phase-14`.
 */
const STAGE = process.env.CAPTURES_STAGE;

test.describe("captures de la phase 14", () => {
  test.skip(!STAGE, "CAPTURES_STAGE non défini");

  for (const scheme of ["light", "dark"] as const) {
    test.describe(scheme === "light" ? "clair" : "sombre", () => {
      test.use({ colorScheme: scheme });

      test.beforeEach(async ({ page }) => {
        await page.goto("/login");
        await page.screenshot({
          path: `../docs/design/captures/phase-14/${STAGE}/${scheme}/connexion.png`,
          animations: "disabled",
        });
        await loginThroughUi(page, DEMO);
        await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
      });

      test("écrans", async ({ page, request }) => {
        test.setTimeout(180_000);
        for (const screen of SCREENS) {
          await screen.open(page, request);
          await settle(page);
          await page.screenshot({
            path: `../docs/design/captures/phase-14/${STAGE}/${scheme}/${screen.name}.png`,
            fullPage: true,
            animations: "disabled",
          });
        }
      });
    });
  }
});
