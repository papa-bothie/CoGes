import { expect, test, type Page } from "@playwright/test";

import { E2E, loginThroughUi, managerApi, stockedProduct } from "./fixtures";

/** Finitions du groupe 1 (prompt 34, bloc F, ADR 0110). */
test.describe.configure({ timeout: 90_000 });

async function login(page: Page) {
  await page.goto("/login");
  await loginThroughUi(page, E2E);
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
}

test("la fiche d'un article montre Modifier et Supprimer, avec une confirmation claire", async ({
  page,
  request,
}) => {
  const client = await managerApi(request);
  const stocked = await stockedProduct(client, { stock: "3" });
  const empty = (await client.post("/products", {
    name: `Sans stock ${crypto.randomUUID().slice(0, 6)}`,
    unit_price: "500",
  })) as { id: string; name: string };
  await login(page);

  await page.goto(`/products/${stocked.id}`);
  await expect(page.getByRole("heading", { level: 1, name: stocked.name })).toBeVisible({
    timeout: 20_000,
  });
  await page.getByRole("link", { name: "Modifier" }).click();
  await expect(page).toHaveURL(new RegExp(`/products/${stocked.id}/edit$`), { timeout: 15_000 });

  // Encore du stock : la base refuse, en mots simples.
  await page.goto(`/products/${stocked.id}`);
  await page.getByRole("button", { name: "Supprimer" }).click();
  await expect(page.getByRole("heading", { name: `Supprimer ${stocked.name} ?` })).toBeVisible();
  await page.getByRole("button", { name: "Oui, supprimer l'article" }).click();
  await expect(page.getByText(/encore du stock : corrigez le stock à zéro/)).toBeVisible();
  await page.getByRole("button", { name: "Annuler" }).click();

  // Sans stock : supprimé, retour au stock.
  await page.goto(`/products/${empty.id}`);
  await page.getByRole("button", { name: "Supprimer" }).click();
  await page.getByRole("button", { name: "Oui, supprimer l'article" }).click();
  await expect(page).toHaveURL(/\/products$/);
  await expect(page.getByText(`${empty.name} est supprimé.`)).toBeVisible();
});

test("la carte « À surveiller » ouvre le stock filtré sur les articles bas et épuisés", async ({
  page,
  request,
}) => {
  const client = await managerApi(request);
  // Seuil d'alerte 1 : à 1 en stock, l'article est bientôt épuisé.
  await stockedProduct(client, { stock: "1" });
  await login(page);

  await page.getByRole("link", { name: "À surveiller", exact: true }).click();
  await expect(page).toHaveURL(/\/products\?filter=watch$/);
  await expect(page.getByRole("button", { name: /^À surveiller \(\d+\)$/ })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await page.goto("/dashboard");
  await page.getByRole("link", { name: "Voir les articles à surveiller" }).click();
  await expect(page).toHaveURL(/\/products\?filter=watch$/);
});

test("les types de dépense s'ajoutent dans un formulaire de la maquette v2", async ({ page }) => {
  const name = `Gardiennage ${crypto.randomUUID().slice(0, 6)}`;
  await login(page);
  await page.goto("/finance/expenses");
  await page.getByRole("button", { name: "Gérer les types de dépense" }).click();
  const dialog = page.getByRole("dialog", { name: "Types de dépense" });
  await dialog.getByLabel("Nom du type").fill(name);
  await dialog.getByRole("radio", { name: "Variable" }).click();
  await dialog.getByRole("button", { name: "Ajouter ce type" }).click();
  await expect(dialog.getByRole("list", { name: "Types de dépense" })).toContainText(name);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("link", { name: "Toutes les dépenses" })).toBeVisible();
});
