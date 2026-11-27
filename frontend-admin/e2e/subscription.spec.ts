import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { addMonths } from "../lib/periods";
import { ADMIN, enterCode } from "./mfa";

function frDate(value: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(value.getUTCDate())}/${pad(value.getUTCMonth() + 1)}/${value.getUTCFullYear()}`;
}

/** Abonnements (ADR 0091, 0132) sur l'entreprise `admin-e2e`, créée par `e2e.sh reset`. */

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

test("abonnement : essai Pro, changement d'offre, paiement d'un an puis de 6 mois, droits acquis", async ({
  page,
}) => {
  await openShop(page);
  const card = page.getByRole("region", { name: "Abonnement" });
  await expect(card).toContainText("Pro");
  await expect(card).toContainText("Essai jusqu'au");
  await axe(page);

  await card.getByLabel("Offre", { exact: true }).selectOption("business");
  await card.getByLabel("Raison", { exact: true }).fill("Le client a choisi Business");
  await card.getByRole("button", { name: "Changer d'offre" }).click();
  await expect(card.getByRole("status")).toHaveText("Offre changée : Business.");
  await expect(card).toContainText(/9.900.FCFA par mois/);

  // Le montant est prérempli ; « 1 an » donne le prix annuel (-10 %).
  await expect(card.getByLabel("Montant (FCFA)")).toHaveValue("9900");
  await card.getByLabel("Durée").selectOption("12");
  await expect(card.getByLabel("Montant (FCFA)")).toHaveValue("106920");
  await card.getByLabel("Moyen").selectOption("orange_money");
  await card.getByLabel("Note").fill("Reçu par Orange Money");
  await card.getByRole("button", { name: "Enregistrer le paiement" }).click();
  await expect(card.getByRole("status")).toContainText("Paiement enregistré.");
  await expect(card.getByText("Actif", { exact: true })).toBeVisible();
  await expect(card.getByRole("cell", { name: "Reçu par Orange Money" })).toBeVisible();
  await expect(card.getByRole("cell", { name: "1 an" })).toBeVisible();
  // L'accès suit l'abonnement : l'entreprise passe « Active ».
  await expect(page.getByText("Active", { exact: true })).toBeVisible();

  // 6 mois, sans remise (ADR 0134) : 6 × 9 900, et la fin avance depuis la fin payée.
  const paidUntil = /Payé jusqu'au (\d{2})\/(\d{2})\/(\d{4})/.exec(
    (await card.getByRole("status").textContent()) ?? "",
  );
  expect(paidUntil).not.toBeNull();
  const [, day, month, year] = paidUntil!.map(Number);
  const expected = addMonths(new Date(Date.UTC(year!, month! - 1, day!, 12)), 6);
  await card.getByLabel("Durée").selectOption("6");
  await expect(card.getByLabel("Montant (FCFA)")).toHaveValue("59400");
  await expect(card).toContainText(`Nouvelle fin : ${frDate(expected)}`);
  await card.getByLabel("Note").fill("Six mois par Wave");
  await card.getByRole("button", { name: "Enregistrer le paiement" }).click();
  await expect(card.getByRole("status")).toContainText(`Payé jusqu'au ${frDate(expected)}.`);
  await expect(card.getByRole("cell", { name: "6 mois" })).toBeVisible();

  // Droits acquis : accordés avec une raison, affichés sur la carte.
  await card.getByRole("checkbox", { name: "Import Excel ou CSV" }).check();
  await card.getByLabel("Raison des droits acquis").fill("Geste commercial");
  await card.getByRole("button", { name: "Enregistrer les droits acquis" }).click();
  await expect(card.getByRole("status")).toHaveText("Droits acquis enregistrés.");
  await expect(card).toContainText("Import Excel ou CSV");
  await axe(page);
});
