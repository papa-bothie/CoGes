import { expect, test, type Page } from "@playwright/test";

import { DEMO, loginThroughUi } from "./fixtures";
import { SCREENS, settle } from "./screens";

/**
 * Captures avant / après de la phase 15, en clair et en sombre
 * (docs/design/captures/phase-15/<CAPTURES_STAGE>/). Ne tourne que si `CAPTURES_STAGE` est
 * défini : `CAPTURES_STAGE=avant pnpm e2e captures-phase-15`. Lot 0 : les écrans touchés
 * par les bugs B1 à B3.
 */
const STAGE = process.env.CAPTURES_STAGE;
const LOT_0 = ["tableau-de-bord", "ventes", "vente-detail", "nouvelle-vente"];

test.describe("captures de la phase 15", () => {
  test.skip(!STAGE, "CAPTURES_STAGE non défini");

  for (const scheme of ["light", "dark"] as const) {
    test.describe(scheme === "light" ? "clair" : "sombre", () => {
      test.use({ colorScheme: scheme });

      async function shoot(page: Page, name: string) {
        await page.screenshot({
          path: `../docs/design/captures/phase-15/${STAGE}/${scheme}/${name}.png`,
          fullPage: true,
          animations: "disabled",
        });
      }

      test.beforeEach(async ({ page }) => {
        await page.goto("/login");
        await loginThroughUi(page, DEMO);
        await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
      });

      test("écrans du lot 0", async ({ page, request }) => {
        test.setTimeout(180_000);
        for (const screen of SCREENS.filter((s) => LOT_0.includes(s.name))) {
          await screen.open(page, request);
          await settle(page);
          await shoot(page, screen.name);
        }

        // B3 : la liste des clients ouverte, là où elle était rognée.
        await page.goto("/sales/new");
        await settle(page);
        await page.getByRole("combobox", { name: /client/i }).click();
        await expect(page.getByRole("option").first()).toBeVisible();
        await shoot(page, "nouvelle-vente-clients");
      });
    });
  }
});
