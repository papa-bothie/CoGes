import { expect, test } from "@playwright/test";

import { DEMO, loginThroughUi } from "./fixtures";

/**
 * Captures de référence de la phase 12 (docs/design/captures/phase-12) : une par écran,
 * sur le jeu de démonstration. Ne vérifie que ce qu'il faut pour que la capture soit
 * prise sur une page **chargée** ; les parcours sont testés dans leurs propres fichiers.
 */
const CAPTURES = "../docs/design/captures/phase-12";

test.describe("captures", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/login");
    await loginThroughUi(page, DEMO);
    await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
  });

  test("tableau de bord", async ({ page }) => {
    await expect(page.getByText(/Chiffres calculés le/)).toBeVisible({ timeout: 30_000 });
    await expect(page.locator(".recharts-surface")).toBeVisible();
    await page.screenshot({ path: `${CAPTURES}/tableau-de-bord.png`, fullPage: true });
  });
});
