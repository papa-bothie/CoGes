import { expect, test, type Page } from "@playwright/test";

import { DEMO, loginThroughUi, managerApi } from "./fixtures";

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

  test("intelligence", async ({ page }) => {
    await page.goto("/insights?status=all");
    await expect(page.getByText(/Données arrêtées au/).first()).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("listitem").first()).toBeVisible({ timeout: 30_000 });
    await shoot(page, "intelligence-recommandations");
    await page
      .getByRole("button", { name: /Écoulement lent/ })
      .first()
      .click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.waitForLoadState("networkidle");
    await shoot(page, "intelligence-panneau");
    await page.keyboard.press("Escape");
    await page.getByRole("tab", { name: "Prévisions" }).click();
    await expect(page.locator(".recharts-surface").first()).toBeVisible({ timeout: 30_000 });
    await shoot(page, "intelligence-previsions");
    await page.goto("/dashboard");
    await expect(page.getByTestId("dashboard-intelligence")).toBeVisible({ timeout: 30_000 });
    await shoot(page, "tableau-de-bord-intelligence");
  });

  test("intelligence désactivée", async ({ page, request }) => {
    const api = await managerApi(request);
    const company = await api.get("/companies/me");
    await api.patch("/companies/me", {
      settings: { ...company.settings, intelligence_enabled: false },
    });
    try {
      await page.goto("/insights");
      await expect(page.getByText("CoGes Intelligence est désactivée")).toBeVisible({
        timeout: 30_000,
      });
      await shoot(page, "intelligence-desactivee");
      await page.goto("/dashboard");
      await expect(page.getByText(/Chiffres calculés le/)).toBeVisible({ timeout: 30_000 });
      await expect(page.getByTestId("dashboard-intelligence")).toHaveCount(0);
    } finally {
      await api.patch("/companies/me", { settings: company.settings });
    }
  });

  test("paramètres", async ({ page }) => {
    await page.goto("/settings");
    await expect(page.getByLabel("Nom de l'entreprise")).toBeVisible({ timeout: 30_000 });
    await shoot(page, "parametres-entreprise");
    // Avertissement avant une modification sensible, sans l'enregistrer.
    await page.getByLabel("Seuil d'alerte par défaut (facultatif)").fill("7");
    await page.getByRole("button", { name: "Enregistrer" }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await shoot(page, "parametres-confirmation");
    await page.getByRole("button", { name: "Annuler" }).click();

    for (const [tab, column, name] of [
      ["Utilisateurs", "Rôles", "parametres-utilisateurs"],
      ["Rôles et permissions", "Permission", "parametres-roles"],
      ["Journal d'activité", "Élément", "parametres-journal"],
    ] as const) {
      await page.getByRole("tab", { name: tab }).click();
      await expect(page.getByRole("columnheader", { name: column }).first()).toBeVisible({
        timeout: 30_000,
      });
      await page.waitForLoadState("networkidle");
      await shoot(page, name);
    }
    await page.getByRole("button", { name: "Voir" }).first().click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await shoot(page, "parametres-journal-detail");
  });

  test("notifications", async ({ page }) => {
    await page.getByRole("button", { name: /^Notifications/ }).click();
    await expect(page.getByRole("dialog", { name: "Notifications" })).toBeVisible();
    await page.waitForLoadState("networkidle");
    await shoot(page, "notifications-panneau");
    await page.getByRole("link", { name: "Toutes les notifications" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Notifications" })).toBeVisible();
    await page.waitForLoadState("networkidle");
    await shoot(page, "notifications-page");
  });
});
