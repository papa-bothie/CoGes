import { expect, test, type Page } from "@playwright/test";

import { E2E, loginThroughUi, managerApi, stockedProduct } from "./fixtures";

const CAPTURES = "../docs/design/captures/phase-12";

test.describe.configure({ timeout: 60_000 });

async function login(page: Page) {
  await page.goto("/login");
  await loginThroughUi(page, E2E);
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
}

test("ajustement de stock avec motif obligatoire, puis correction", async ({ page, request }) => {
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

  await page.getByRole("button", { name: "Nouveau mouvement" }).click();
  const dialog = page.getByRole("dialog");
  await dialog
    .getByRole("combobox", { name: "Rechercher un article (nom ou SKU)" })
    .fill(product.name);
  await page.getByRole("option", { name: new RegExp(product.name) }).click();
  await expect(dialog.getByText("Stock actuel : 10")).toBeVisible();

  await dialog.getByRole("combobox", { name: "Type de mouvement" }).click();
  await page.getByRole("option", { name: "Ajustement" }).click();
  await dialog.getByRole("radio", { name: "Sortie (−)" }).click();
  await dialog.getByLabel("Quantité").fill("3");

  // Sans motif : refus avant tout envoi, près du champ.
  await dialog.getByRole("button", { name: "Enregistrer le mouvement" }).click();
  await expect(dialog.getByText("Ce champ est obligatoire.")).toBeVisible();
  await page.screenshot({ path: `${CAPTURES}/mouvement-motif.png`, animations: "disabled" });

  await dialog.getByLabel("Motif (obligatoire)").fill("Inventaire du 30/09 : 3 unités manquantes");
  await dialog.getByRole("button", { name: "Enregistrer le mouvement" }).click();
  await expect(page.getByText("Mouvement enregistré.")).toBeVisible();
  await expect(dialog).toBeHidden();

  const stock = await client.get(`/inventory/stock?product_id=${product.id}`);
  expect(stock.items[0].qty_on_hand).toBe("7.000");

  // Journal filtré sur l'article : l'ajustement et son motif.
  await page.getByRole("tab", { name: "Journal des mouvements" }).click();
  await page.getByRole("combobox", { name: "Filtrer par article" }).fill(product.name);
  await page.getByRole("option", { name: new RegExp(product.name) }).click();
  await expect(page).toHaveURL(/product=/);
  await expect(page.getByText(/^2 éléments$/)).toBeVisible();
  const adjustment = page.getByRole("row").filter({ hasText: "Ajustement" });
  await expect(adjustment).toContainText("-3");
  await expect(adjustment).toContainText("3 unités manquantes");
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
