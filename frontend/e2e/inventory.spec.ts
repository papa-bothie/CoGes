import { expect, test, type Page } from "@playwright/test";

import { E2E, loginThroughUi, managerApi, stockedProduct } from "./fixtures";

const CAPTURES = "../docs/design/captures/phase-12";

test.describe.configure({ timeout: 60_000 });

async function login(page: Page) {
  await page.goto("/login");
  await loginThroughUi(page, E2E);
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
}

test("corriger le stock avec une raison en tuile, puis l'annuler", async ({ page, request }) => {
  const client = await managerApi(request);
  const product = await stockedProduct(client, { stock: "10" });
  await login(page);

  await page.goto("/inventory");
  await expect(page.getByRole("tab", { name: "Stock courant" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(page.getByText(/\d+ articles? suivis?/)).toBeVisible({ timeout: 30_000 });
  await page.screenshot({ path: `${CAPTURES}/stock.png`, fullPage: true, animations: "disabled" });

  await page.getByRole("button", { name: "Corriger le stock" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Chercher un article").fill(product.name);
  await dialog.getByRole("button", { name: new RegExp(product.name) }).click();
  await expect(dialog.getByText("Le logiciel compte")).toContainText("10 pièces");

  await dialog.getByRole("radio", { name: "Moins" }).click();
  await dialog.getByLabel(`Quantité : ${product.name}`).fill("3");
  await expect(dialog.getByRole("status")).toContainText("Après : 7 pièces");
  // Sans raison, le bouton reste grisé : on ne tape jamais de motif.
  const submit = dialog.getByRole("button", { name: "Valider la correction" });
  await expect(submit).toBeDisabled();
  await page.screenshot({ path: `${CAPTURES}/mouvement-motif.png`, animations: "disabled" });
  await dialog.getByRole("radio", { name: "Erreur de comptage" }).click();
  await submit.click();
  await expect(page.getByText("Stock corrigé.")).toBeVisible();
  await expect(dialog).toBeHidden();

  const stock = await client.get(`/inventory/stock?product_id=${product.id}`);
  expect(stock.items[0].qty_on_hand).toBe("7.000");

  // Journal filtré sur l'article : l'ajustement et sa raison en toutes lettres.
  await page.getByRole("tab", { name: "Journal des mouvements" }).click();
  await page.getByRole("combobox", { name: "Filtrer par article" }).fill(product.name);
  await page.getByRole("option", { name: new RegExp(product.name) }).click();
  await expect(page).toHaveURL(/product=/);
  await expect(page.getByText(/^2 éléments$/)).toBeVisible();
  const adjustment = page.getByRole("row").filter({ hasText: "Ajustement" });
  await expect(adjustment).toContainText("-3");
  await expect(adjustment).toContainText("Erreur de comptage");
  await page.screenshot({
    path: `${CAPTURES}/journal.png`,
    fullPage: true,
    animations: "disabled",
  });

  // Correction par le mouvement inverse (ADR 0017).
  await adjustment.getByRole("button", { name: "Corriger" }).click();
  await page.getByRole("button", { name: "Enregistrer l'inverse" }).click();
  await expect(page.getByText("Mouvement corrigé par son inverse.")).toBeVisible();
  await expect(page.getByRole("row").filter({ hasText: "Annulation" })).toContainText("+3");
  const restored = await client.get(`/inventory/stock?product_id=${product.id}`);
  expect(restored.items[0].qty_on_hand).toBe("10.000");
});
