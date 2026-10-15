import { expect, test, type Page } from "@playwright/test";

import { E2E, loginThroughUi, managerApi, stockedProduct } from "./fixtures";

/**
 * Réglages, lot 3e-2 (ADR 0075) : la grille « Qui peut faire quoi » change les droits du
 * vendeur, une personne ajoutée reçoit un mot de passe provisoire puis perd et retrouve
 * son accès, le reçu s'ouvre dans le format choisi, et l'Historique raconte en phrases.
 */
test.describe.configure({ timeout: 90_000 });

async function login(page: Page) {
  await page.goto("/login");
  await loginThroughUi(page, E2E);
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
}

type Grid = { roles: { role_id: string; name: string; abilities: string[] }[] };

test("cocher « Corriger le stock » donne ses droits au vendeur", async ({ page, request }) => {
  const client = await managerApi(request);
  const grid = (await client.get("/roles/abilities")) as Grid;
  const seller = grid.roles.find((role) => role.name === "vendeur")!;
  try {
    await login(page);
    await page.goto("/settings/rights");
    const cell = page.getByRole("button", { name: "Corriger le stock : Vendeur" });
    await expect(cell).toHaveAttribute("aria-pressed", "false");
    await cell.click();
    await expect(cell).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByText("Droits enregistrés.")).toBeVisible();
    const role = await client.get(`/roles/${seller.role_id}`);
    expect(role.permissions).toEqual(
      expect.arrayContaining(["inventory:create", "inventory:update"]),
    );
    // Le gérant garde tout : sa colonne ne se clique pas.
    await expect(page.getByRole("button", { name: "Vendre : Gérant" })).toBeDisabled();
    await expect(
      page.getByRole("button", { name: "Gérer les personnes : Vendeur" }),
    ).toBeDisabled();
  } finally {
    await client.put(`/roles/${seller.role_id}/abilities`, { abilities: seller.abilities });
  }
});

test("ajouter une personne, couper son accès puis le lui redonner", async ({ page }) => {
  await login(page);
  await page.goto("/settings/people");
  await page.getByRole("button", { name: "+ Ajouter une personne" }).click();
  const name = `Awa ${crypto.randomUUID().slice(0, 6)}`;
  await page.getByLabel("Nom", { exact: true }).fill(name);
  const digits = `77${String(Date.now()).slice(-7)}`;
  await page.getByLabel("Téléphone ou e-mail").fill(digits);
  await page.getByRole("button", { name: "Vendeur" }).click();
  await page.getByRole("button", { name: "Créer son accès" }).click();
  await expect(
    page.getByRole("status").filter({ hasText: "Mot de passe provisoire" }),
  ).toContainText(/[A-Z]+-\d{4}-[A-Z]+/);

  // Dans la page, pas dans la notification « Accès créé pour … ».
  const row = page.getByRole("main").getByRole("listitem").filter({ hasText: name });
  await expect(row).toContainText("Vendeur · Jamais connecté");
  await row.getByRole("button", { name: "Couper l’accès" }).click();
  await expect(row).toContainText(/Accès coupé le \d+/);
  await row.getByRole("button", { name: "Redonner l’accès" }).click();
  await expect(row).toContainText("Jamais connecté");
});

test("le reçu s'ouvre dans le format choisi dans Ma boutique", async ({ page, request }) => {
  const client = await managerApi(request);
  const company = await client.get("/companies/me");
  const product = await stockedProduct(client, { stock: "5" });
  const sale = await client.post("/sales", {});
  await client.post(`/sales/${sale.id}/items`, { product_id: product.id, qty: "1" });
  await client.post(`/sales/${sale.id}/confirm`, { paid_amount: "1000", method: "cash" });
  try {
    await login(page);
    await page.goto("/settings");
    await page.getByRole("button", { name: "Facture A4" }).click();
    await page.getByRole("button", { name: "Enregistrer" }).click();
    await expect(page.getByText("Réglages enregistrés.")).toBeVisible();

    await page.goto(`/sales/${sale.id}/receipt`);
    await expect(page.getByRole("button", { name: "Facture A4" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  } finally {
    await client.patch("/companies/me", { settings: company.settings });
  }
});

test("l'Historique raconte un changement de prix en une phrase", async ({ page, request }) => {
  const client = await managerApi(request);
  const product = await stockedProduct(client, { stock: "5" });
  await client.post(`/products/${product.id}/prices`, { unit_price: "1500" });
  await login(page);
  await page.goto("/settings/history");
  await expect(
    page.getByText(
      new RegExp(`a changé le prix d(e |’)${product.name} : 1\\s000\\sFCFA → 1\\s500\\sFCFA`),
    ),
  ).toBeVisible({ timeout: 30_000 });
});

test("les anciens onglets mènent à leur rubrique", async ({ page }) => {
  await login(page);
  await page.goto("/settings?tab=roles");
  await expect(page).toHaveURL(/\/settings\/rights$/);
  await expect(page.getByRole("heading", { name: "Qui peut faire quoi" })).toBeVisible();
});
