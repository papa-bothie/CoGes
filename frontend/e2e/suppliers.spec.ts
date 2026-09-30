import { expect, test, type Page } from "@playwright/test";

import { DEMO, loginThroughUi, managerApi } from "./fixtures";

const CAPTURES = "../docs/design/captures/phase-12";

test.describe.configure({ timeout: 90_000 });

async function login(page: Page) {
  await page.goto("/login");
  await loginThroughUi(page, DEMO);
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
}

test("fiche fournisseur : délai de paiement, charges et dettes", async ({ page, request }) => {
  const client = await managerApi(request);
  const marker = crypto.randomUUID().slice(0, 6);
  const name = `Grossiste ${marker}`;
  await login(page);

  await page.goto("/suppliers");
  await page.getByRole("button", { name: "Nouveau fournisseur" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Nom", { exact: true }).fill(name);
  // Hors bornes : refusé avant tout envoi, près du champ.
  await dialog.getByLabel("Délai de paiement en jours (facultatif)").fill("400");
  await dialog.getByRole("button", { name: "Enregistrer" }).click();
  await expect(dialog.getByText("Un nombre entier de jours, de 0 à 365.")).toBeVisible();
  await dialog.getByLabel("Délai de paiement en jours (facultatif)").fill("30");
  await dialog.getByRole("button", { name: "Enregistrer" }).click();

  await expect(page).toHaveURL(/\/suppliers\/[0-9a-f-]+$/);
  await expect(page.getByText("30 jours")).toBeVisible();
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
  await expect(page.getByRole("row").filter({ hasText: name })).toContainText("30 jours");
  await page.screenshot({
    path: `${CAPTURES}/fournisseurs.png`,
    fullPage: true,
    animations: "disabled",
  });
});
