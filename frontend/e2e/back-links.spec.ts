import { expect, test, type Page } from "@playwright/test";

import { E2E, loginThroughUi, managerApi, stockedProduct } from "./fixtures";

/** Le lien « ← … » des écrans d'action ramène d'où l'on vient (ADR 0082). */

test.describe.configure({ timeout: 60_000 });

async function login(page: Page) {
  await page.goto("/login");
  await loginThroughUi(page, E2E);
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
}

test("sans origine, chaque écran d'action ramène à sa rubrique", async ({ page }) => {
  await login(page);
  for (const [path, label, parent] of [
    ["/finance/cash", "L'argent", "/finance"],
    ["/finance/collect", "L'argent", "/finance"],
    ["/finance/pay", "L'argent", "/finance"],
    ["/finance/expenses", "L'argent", "/finance"],
    ["/inventory/adjust", "Stock", "/products"],
    ["/inventory/receive", "Stock", "/products"],
  ] as const) {
    await page.goto(path);
    await expect(page.getByRole("link", { name: label, exact: true }).last()).toHaveAttribute(
      "href",
      parent,
    );
  }
});

test("la caisse ouverte depuis Conseils y ramène, même après avoir changé de jour", async ({
  page,
}) => {
  await login(page);
  await page.goto("/finance/cash?from=%2Finsights");
  await page.getByRole("button", { name: "Hier", exact: true }).click();
  await expect(page).toHaveURL(/day=.*from=%2Finsights|from=%2Finsights.*day=/);
  await page.getByRole("link", { name: "Conseils", exact: true }).last().click();
  await expect(page).toHaveURL(/\/insights$/);
});

test("une origine hors de CoGes est ignorée", async ({ page }) => {
  await login(page);
  await page.goto("/finance/cash?from=https%3A%2F%2Fevil.example%2F");
  await expect(page.getByRole("link", { name: "L'argent", exact: true }).last()).toHaveAttribute(
    "href",
    "/finance",
  );
});

test("depuis la fiche d'un article, corriger et recevoir ramènent à la fiche", async ({
  page,
  request,
}) => {
  const client = await managerApi(request);
  const product = await stockedProduct(client, { stock: "5" });
  await login(page);

  for (const action of ["Corriger le stock", "Commander"]) {
    await page.goto(`/products/${product.id}`);
    await page.getByRole("link", { name: action, exact: true }).click();
    await expect(page).toHaveURL(/\/inventory\/(adjust|receive)\?product=.*from=/);
    await page.getByRole("link", { name: product.name, exact: true }).first().click();
    await expect(page).toHaveURL(new RegExp(`/products/${product.id}$`));
  }
});

test("modifier un article ramène à sa fiche", async ({ page, request }) => {
  const client = await managerApi(request);
  const product = await stockedProduct(client, { stock: "1" });
  await login(page);
  await page.goto(`/products/${product.id}/edit`);
  await page.getByRole("link", { name: product.name, exact: true }).first().click();
  await expect(page).toHaveURL(new RegExp(`/products/${product.id}$`));
});
