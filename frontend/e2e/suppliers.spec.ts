import { expect, test, type Page } from "@playwright/test";

import { E2E, loginThroughUi, managerApi } from "./fixtures";

const CAPTURES = "../docs/design/captures/phase-12";

test.describe.configure({ timeout: 90_000 });

async function login(page: Page) {
  await page.goto("/login");
  await loginThroughUi(page, E2E);
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
}

test("ajouter un fournisseur ; sa fiche montre charges et dettes", async ({ page, request }) => {
  const client = await managerApi(request);
  const marker = crypto.randomUUID().slice(0, 6);
  const name = `Grossiste ${marker}`;
  await login(page);

  await page.goto("/suppliers");
  await page.getByRole("button", { name: "Ajouter une personne" }).click();
  const dialog = page.getByRole("dialog");
  // La liste des fournisseurs ouvre le formulaire sur « Un fournisseur » ; plus de délai.
  await expect(dialog.getByRole("radio", { name: "Un fournisseur" })).toBeChecked();
  await dialog.getByLabel("Nom du fournisseur").fill(name);
  await dialog.getByRole("button", { name: "Enregistrer le fournisseur" }).click();

  await expect(page).toHaveURL(/\/suppliers\/[0-9a-f-]+$/);
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
  const supplierId = page.url().split("/").pop()!;

  // Une charge et une dette rattachées, saisies par l'API.
  const category = await client.post("/expense-categories", {
    name: `Achats ${marker}`,
    kind: "variable",
  });
  await client.post("/expenses", {
    category_id: category.id,
    label: `Livraison ${marker}`,
    amount: "25000",
    spent_at: new Date().toISOString().slice(0, 10),
    supplier_id: supplierId,
  });
  await client.post("/debts", {
    party_type: "supplier",
    supplier_id: supplierId,
    principal: "80000",
  });

  await page.reload();
  await expect(page.getByRole("row").filter({ hasText: `Livraison ${marker}` })).toContainText(
    /25\s000\sFCFA/,
  );
  await expect(
    page.getByRole("row").filter({ has: page.getByRole("cell", { name: "Ouverte", exact: true }) }),
  ).toContainText(/80\s000\sFCFA/);
  await page.screenshot({
    path: `${CAPTURES}/fiche-fournisseur.png`,
    fullPage: true,
    animations: "disabled",
  });

  await page.goto("/suppliers");
  await expect(page.getByText(/\d+ fournisseurs?/)).toBeVisible();
  await expect(page.getByRole("row").filter({ hasText: name })).toBeVisible();
  await page.screenshot({
    path: `${CAPTURES}/fournisseurs.png`,
    fullPage: true,
    animations: "disabled",
  });
});
