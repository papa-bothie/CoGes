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

  // L'écran Stock (maquette 07) mène à la correction (maquette 10).
  await page.goto("/products");
  await expect(page.getByText(/\d+ articles? · votre stock vaut/)).toBeVisible({
    timeout: 30_000,
  });
  await page.screenshot({ path: `${CAPTURES}/stock.png`, fullPage: true, animations: "disabled" });
  await page.getByRole("link", { name: "Corriger le stock" }).click();
  await expect(page).toHaveURL(/\/inventory\/adjust$/);

  await page.goto(`/inventory/adjust?product=${product.id}`);
  await expect(page.getByRole("radio", { name: new RegExp(product.name) })).toHaveAttribute(
    "aria-checked",
    "true",
  );
  await expect(page.getByText("Le logiciel compte")).toContainText("10 pièces");
  // « Moins » et « Abîmé ou cassé » sont choisis d'office : on ne tape jamais de motif.
  await expect(page.getByRole("radio", { name: "Moins", exact: true })).toHaveAttribute(
    "aria-checked",
    "true",
  );
  await page.getByLabel(`Quantité : ${product.name}`).fill("3");
  await expect(page.getByRole("status").filter({ hasText: "Après" })).toContainText(
    "Après : 7 pièces",
  );
  await page.screenshot({ path: `${CAPTURES}/mouvement-motif.png`, animations: "disabled" });
  await page.getByRole("radio", { name: "Erreur de comptage" }).click();
  await page.getByRole("button", { name: "Valider la correction" }).click();
  await expect(page.getByText(`${product.name} : 7 pièces maintenant`)).toBeVisible();

  const stock = await client.get(`/inventory/stock?product_id=${product.id}`);
  expect(stock.items[0].qty_on_hand).toBe("7.000");

  // « Tous les mouvements », filtré sur l'article : l'ajustement et sa raison.
  await page.goto("/products");
  await page.getByRole("link", { name: "Tous les mouvements" }).click();
  await expect(page).toHaveURL(/\/inventory$/);
  await page.getByRole("combobox", { name: "Filtrer par article" }).fill(product.name);
  await page.getByRole("option", { name: new RegExp(product.name) }).click();
  await expect(page).toHaveURL(/product=/);
  await expect(page.getByText(/^2 éléments$/)).toBeVisible();
  const adjustment = page.getByRole("main").getByRole("listitem").filter({ hasText: "Ajustement" });
  await expect(adjustment).toContainText("−3");
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
  await expect(
    page.getByRole("main").getByRole("listitem").filter({ hasText: "Annulation" }),
  ).toContainText("+3");
  const restored = await client.get(`/inventory/stock?product_id=${product.id}`);
  expect(restored.items[0].qty_on_hand).toBe("10.000");
});

test("recevoir une livraison payée en partie : stock, dette et sortie de caisse", async ({
  page,
  request,
}) => {
  const client = await managerApi(request);
  const product = await stockedProduct(client, { stock: "2" });
  const supplier = `Grossiste ${crypto.randomUUID().slice(0, 6)}`;
  await login(page);

  // « Commander » sur la fiche ouvre la livraison avec l'article déjà ajouté.
  await page.goto(`/products/${product.id}`);
  await page.getByRole("link", { name: "Commander" }).click();
  await expect(page).toHaveURL(/\/inventory\/receive\?product=/);
  await expect(page.getByLabel(`Quantité : ${product.name}`)).toBeVisible();

  await page.getByRole("button", { name: "+ Nouveau fournisseur" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Nom du fournisseur").fill(supplier);
  await dialog.getByRole("button", { name: "Enregistrer le fournisseur" }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByRole("button", { name: supplier, exact: true })).toHaveAttribute(
    "aria-pressed",
    "true",
  );

  await page.getByLabel(`Quantité : ${product.name}`).fill("10");
  await page.getByLabel(`Prix d'achat (F) : ${product.name}`).fill("700");
  await expect(page.getByText(/^7\s000\sF$/).first()).toBeVisible();
  await page.getByRole("button", { name: "Une partie", exact: true }).click();
  await page.getByLabel("Vous donnez maintenant").fill("3000");
  await expect(page.getByText(/Il restera 4\s000\sF à payer/)).toBeVisible();
  await page.getByRole("button", { name: "Enregistrer la livraison" }).click();
  await expect(page.getByRole("heading", { name: "Livraison enregistrée" })).toBeVisible();
  await expect(page.getByText(new RegExp(`Vous devez 4\\s000\\sF à ${supplier}`))).toBeVisible();

  // Une seule écriture : le stock, la dette fournisseur et l'argent sorti.
  const stock = await client.get(`/inventory/stock?product_id=${product.id}`);
  expect(stock.items[0].qty_on_hand).toBe("12.000");
  const found = await client.get(`/suppliers?search=${encodeURIComponent(supplier)}`);
  const debts = await client.get(`/debts?supplier_id=${found.items[0].id}`);
  expect(debts.items).toHaveLength(1);
  expect(debts.items[0].principal).toBe("7000.00");
  expect(debts.items[0].balance).toBe("4000.00");
});
