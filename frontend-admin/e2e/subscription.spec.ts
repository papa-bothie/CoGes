import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { ADMIN, enterCode } from "./mfa";

/** Abonnements (ADR 0091) sur l'entreprise `admin-e2e`, créée par `e2e.sh reset`. */

async function openShop(page: Page): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("E-mail").fill(ADMIN.email);
  await page.getByLabel("Mot de passe", { exact: true }).fill(ADMIN.password);
  await page.getByRole("button", { name: "Se connecter" }).click();
  await enterCode(page);
  await expect(page.getByRole("heading", { name: "Tableau de bord" })).toBeVisible();
  await page.goto("/companies");
  await page.getByLabel("Nom ou code").fill("admin-e2e");
  await page.getByRole("button", { name: "Chercher" }).click();
  await page.getByRole("link", { name: "Parcours administration" }).click();
  await expect(page.getByRole("heading", { name: "Abonnement" })).toBeVisible();
}

async function axe(page: Page): Promise<void> {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  expect(results.violations).toEqual([]);
}

test("abonnement : essai Premium, changement d'offre, paiement enregistré", async ({ page }) => {
  await openShop(page);
  const card = page.getByRole("region", { name: "Abonnement" });
  await expect(card).toContainText("Premium");
  await expect(card).toContainText("Essai jusqu'au");
  await axe(page);

  await card.getByLabel("Offre", { exact: true }).selectOption("business");
  await card.getByLabel("Raison", { exact: true }).fill("Le client a choisi Business");
  await card.getByRole("button", { name: "Changer d'offre" }).click();
  await expect(card.getByRole("status")).toHaveText("Offre changée : Business.");
  await expect(card).toContainText(/9.900.FCFA par mois/);

  await card.getByLabel("Montant (FCFA)").fill("9900");
  await card.getByLabel("Moyen").selectOption("orange_money");
  await card.getByLabel("Note").fill("Reçu par Orange Money");
  await card.getByRole("button", { name: "Enregistrer le paiement" }).click();
  await expect(card.getByRole("status")).toContainText("Paiement enregistré.");
  await expect(card.getByText("Actif", { exact: true })).toBeVisible();
  await expect(card.getByRole("cell", { name: "Reçu par Orange Money" })).toBeVisible();
  // L'accès suit l'abonnement : l'entreprise passe « Active ».
  await expect(page.getByText("Active", { exact: true })).toBeVisible();
  await axe(page);
});
