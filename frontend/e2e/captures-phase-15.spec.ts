import { expect, test, type Page } from "@playwright/test";

import { DEMO, loginThroughUi } from "./fixtures";
import { SCREENS, settle } from "./screens";

/**
 * Captures avant / après de la phase 15, en clair et en sombre
 * (docs/design/captures/phase-15/<CAPTURES_STAGE>/). Ne tourne que si `CAPTURES_STAGE` est
 * défini : `CAPTURES_STAGE=avant pnpm e2e captures-phase-15`. Lot 0 : les écrans touchés
 * par les bugs B1 à B3. `CAPTURES_LOT=F` : le thème change partout, donc tous les écrans,
 * plus la connexion, dans le sous-dossier `lot-f/`.
 */
const STAGE = process.env.CAPTURES_STAGE;
const LOT = process.env.CAPTURES_LOT ?? "0";
const LOT_0 = ["tableau-de-bord", "ventes", "vente-detail", "nouvelle-vente"];
const FOLDER = LOT === "0" ? "" : `/lot-${LOT.toLowerCase()}`;

test.describe("captures de la phase 15", () => {
  test.skip(!STAGE, "CAPTURES_STAGE non défini");

  for (const scheme of ["light", "dark"] as const) {
    test.describe(scheme === "light" ? "clair" : "sombre", () => {
      test.use({ colorScheme: scheme });

      async function shoot(page: Page, name: string) {
        await page.screenshot({
          path: `../docs/design/captures/phase-15/${STAGE}/${scheme}${FOLDER}/${name}.png`,
          fullPage: true,
          animations: "disabled",
        });
      }

      test("connexion", async ({ page }) => {
        test.skip(LOT === "0", "lot 0 : écran non touché");
        await page.context().clearCookies();
        await page.goto("/login");
        await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
        await page.waitForLoadState("networkidle");
        await shoot(page, "connexion");
      });

      test("vitrine des composants", async ({ page }) => {
        test.skip(LOT !== "F", "lot F seulement");
        await page.goto("/dev/composants");
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible({ timeout: 60_000 });
        await page.waitForLoadState("networkidle");
        await shoot(page, "composants");
      });

      test.beforeEach(async ({ page }, info) => {
        if (info.title === "connexion" || info.title === "vitrine des composants") return;
        await page.goto("/login");
        await loginThroughUi(page, DEMO);
        await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
      });

      test("écrans du lot", async ({ page, request }) => {
        test.setTimeout(400_000);
        const screens = LOT === "0" ? SCREENS.filter((s) => LOT_0.includes(s.name)) : SCREENS;
        for (const screen of screens) {
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
