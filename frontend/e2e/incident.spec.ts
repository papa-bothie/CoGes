import { expect, test, type Page } from "@playwright/test";

import { E2E, emptyMyDrafts, loginThroughUi, managerApi, stockedProduct } from "./fixtures";

/**
 * Pannes vues par le commerçant (ADR 0085) : une coupure pendant une lecture affiche un
 * bandeau puis se résout seule ; une écriture qui échoue garde la saisie et, rejouée,
 * n'écrit qu'une fois (même clé d'idempotence).
 */

test.describe.configure({ timeout: 90_000, mode: "serial" });

test.beforeEach(async ({ request }) => {
  await emptyMyDrafts(request);
});

async function login(page: Page) {
  await page.goto("/login");
  await loginThroughUi(page, E2E);
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
}

test("API coupée pendant une lecture : bandeau, puis retour à la normale", async ({ page }) => {
  await login(page);
  await page.goto("/customers");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible({ timeout: 30_000 });

  // Les lectures échouent comme si le réseau tombait ; la session, elle, reste valide.
  const cut = (route: import("@playwright/test").Route) =>
    route.request().method() === "GET" && !route.request().url().includes("/auth/")
      ? route.abort("internetdisconnected")
      : route.continue();
  await page.route("**/api/v1/**", cut);
  await page.getByRole("link", { name: "Stock", exact: true }).first().click();

  const banner = page.getByRole("status").filter({ hasText: "Connexion difficile" });
  await expect(banner).toContainText("Nous réessayons", { timeout: 20_000 });

  await page.unroute("**/api/v1/**", cut);
  await expect(banner).toHaveCount(0, { timeout: 20_000 });
  await expect(page.getByText(/votre stock vaut/)).toBeVisible();
});

test("500 sur la confirmation : panier gardé, et le rejeu n'enregistre qu'une vente", async ({
  page,
  request,
}) => {
  const client = await managerApi(request);
  const product = await stockedProduct(client, { stock: "10" });
  await login(page);

  await page.goto("/sales/new");
  await page.getByRole("searchbox", { name: "Chercher un article" }).fill(product.name);
  await page.getByRole("button", { name: `Ajouter ${product.name}` }).click();
  const qty = page.getByRole("textbox", { name: `Quantité de ${product.name}` });
  await qty.fill("2");
  await qty.press("Enter");
  await expect(qty).toHaveValue("2");
  await page.waitForLoadState("networkidle");

  // La première confirmation ATTEINT le serveur (la vente est enregistrée), mais sa
  // réponse se perd et le navigateur reçoit une 500 : le pire cas pour un double envoi.
  let confirms = 0;
  await page.route("**/api/v1/sales/*/confirm", async (route) => {
    confirms += 1;
    if (confirms > 1) return route.continue();
    await route.fetch();
    await route.fulfill({
      status: 500,
      contentType: "application/json",
      headers: { "x-request-id": "ab12cd34-0000-0000-0000-000000000000" },
      body: JSON.stringify({
        error: {
          code: "server_error",
          message:
            "Un souci de notre côté. Vos données sont en sécurité. Réessayez dans un instant.",
          details: {},
          request_id: "ab12cd34-0000-0000-0000-000000000000",
        },
      }),
    });
  });

  const pay = page.getByRole("button", { name: /^Encaisser 2\s000\sF$/ });
  await pay.click();
  await expect(page.getByText(/Un souci de notre côté/)).toBeVisible({ timeout: 30_000 });
  // Rien n'est rejoué tout seul, et le panier est intact.
  expect(confirms).toBe(1);
  await expect(qty).toHaveValue("2");

  await pay.click();
  await expect(page.getByRole("heading", { name: "Vente enregistrée" })).toBeVisible();
  expect(confirms).toBe(2);

  // Une seule sortie de stock : 10 − 2, et non 10 − 4.
  const stock = await client.get(`/inventory/stock?product_id=${product.id}`);
  expect(stock.items[0].qty_on_hand).toBe("8.000");
});
