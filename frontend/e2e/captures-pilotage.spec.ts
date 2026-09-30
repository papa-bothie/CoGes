import { expect, test, type Page } from "@playwright/test";

import { DEMO, loginThroughUi } from "./fixtures";

/**
 * Captures de référence de la phase 13 (docs/design/captures/phase-13), sur le jeu de
 * démonstration. Les parcours sont vérifiés dans leurs propres fichiers.
 */
const CAPTURES = "../docs/design/captures/phase-13";

async function shoot(page: Page, name: string) {
  await page.screenshot({
    path: `${CAPTURES}/${name}.png`,
    fullPage: true,
    animations: "disabled",
  });
}

test.describe("captures du pilotage", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/login");
    await loginThroughUi(page, DEMO);
    await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
  });

  test("finance", async ({ page }) => {
    await page.goto("/finance");
    await expect(page.getByText("Encaissements").first()).toBeVisible({ timeout: 30_000 });
    await expect(
      page.locator(".recharts-surface").or(page.getByText(/Aucun mouvement/)),
    ).toBeVisible({
      timeout: 30_000,
    });
    await shoot(page, "finance-vue-ensemble");

    for (const [tab, column, name] of [
      ["Paiements", "Objet", "finance-paiements"],
      ["Dettes", "Tiers", "finance-dettes"],
      ["Dépenses", "Libellé", "finance-depenses"],
    ] as const) {
      await page.getByRole("tab", { name: tab }).click();
      await expect(page.getByRole("columnheader", { name: column })).toBeVisible({
        timeout: 30_000,
      });
      await page.waitForLoadState("networkidle");
      await shoot(page, name);
      if (tab === "Dettes") {
        await page.getByRole("button", { name: "Régler" }).nth(2).click();
        await page.getByRole("button", { name: "Répartir" }).waitFor();
        await page.getByLabel("Montant versé").fill("30000");
        await page.getByRole("button", { name: "Répartir" }).click();
        await shoot(page, "finance-reglement-reparti");
        await page.keyboard.press("Escape");
      }
    }
  });

  test("analytics", async ({ page }) => {
    await page.goto("/analytics");
    await expect(page.getByTestId("ranking-leader")).toBeVisible({ timeout: 30_000 });
    await page.waitForLoadState("networkidle");
    await shoot(page, "analytics-ca");
    await page.goto("/analytics?metric=future_potential");
    await expect(page.getByTestId("ranking-title")).toContainText("potentiel futur", {
      timeout: 30_000,
    });
    await page.waitForLoadState("networkidle");
    await shoot(page, "analytics-potentiel-futur");
  });
});
