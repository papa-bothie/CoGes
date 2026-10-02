import { expect, test, type Page } from "@playwright/test";

import {
  createSalesperson,
  E2E,
  loginThroughUi,
  managerApi,
  stockedProduct,
  type ManagerApi,
} from "./fixtures";

const CAPTURES = "../docs/design/captures/phase-12";

test.describe.configure({ timeout: 90_000 });

async function login(page: Page, credentials = E2E) {
  await page.goto("/login");
  await loginThroughUi(page, credentials);
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
}

async function creditSale(client: ManagerApi, customerId: string) {
  const product = await stockedProduct(client, { stock: "5" });
  const sale = await client.post("/sales", { customer_id: customerId });
  await client.post(`/sales/${sale.id}/items`, { product_id: product.id, qty: "2", discount: "0" });
  await client.post(`/sales/${sale.id}/confirm`, { paid_amount: "500", method: "cash" });
  return sale as { id: string; sale_no: string };
}

test("fiche client : encours, achats, dettes ; code en double refusé", async ({
  page,
  request,
}) => {
  const client = await managerApi(request);
  const marker = crypto.randomUUID().slice(0, 6);
  const name = `Boutique ${marker}`;
  await login(page);

  await page.goto("/customers");
  await page.getByRole("button", { name: "Nouveau client" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Nom", { exact: true }).fill(name);
  await dialog.getByLabel("Code (facultatif, généré sinon)").fill(`CLI-${marker}`);
  await dialog.getByLabel("Téléphone (facultatif)").fill("+221 77 000 00 00");
  await dialog.getByLabel("Encours autorisé (facultatif)").fill("50000");
  await dialog.getByRole("button", { name: "Enregistrer" }).click();

  await expect(page).toHaveURL(/\/customers\/[0-9a-f-]+$/);
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
  const customerId = page.url().split("/").pop()!;
  const sale = await creditSale(client, customerId);

  await page.reload();
  await expect(page.getByRole("link", { name: new RegExp(sale.sale_no) })).toBeVisible();
  const debt = page
    .getByRole("row")
    .filter({ has: page.getByRole("cell", { name: "Ouverte", exact: true }) });
  await expect(debt).toContainText(/1\s500\sFCFA/);
  await page.screenshot({
    path: `${CAPTURES}/fiche-client.png`,
    fullPage: true,
    animations: "disabled",
  });

  // Un second client ne peut pas reprendre le même code : refus près du champ.
  await page.goto("/customers");
  await page.getByRole("button", { name: "Nouveau client" }).click();
  await dialog.getByLabel("Nom", { exact: true }).fill(`Autre ${marker}`);
  await dialog.getByLabel("Code (facultatif, généré sinon)").fill(`CLI-${marker}`);
  await dialog.getByRole("button", { name: "Enregistrer" }).click();
  await expect(dialog.getByRole("alert").first()).toBeVisible();
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Fermer", exact: true }).click();

  await page.getByRole("searchbox").fill(name);
  await expect(page.getByRole("row").filter({ hasText: name })).toContainText(/50\s000\sFCFA/);
  await page.getByRole("searchbox").fill("");
  await expect(page.getByText(/^\d+ clients?$/)).toBeVisible();
  await page.screenshot({
    path: `${CAPTURES}/clients.png`,
    fullPage: true,
    animations: "disabled",
  });
});

test("un vendeur voit la fiche client sans les dettes", async ({ page, request }) => {
  const client = await managerApi(request);
  const customer = await client.post("/customers", {
    name: `Client vendeur ${crypto.randomUUID().slice(0, 6)}`,
  });
  await login(page, await createSalesperson(request));
  await page.goto(`/customers/${customer.id}`);
  await expect(page.getByText("Historique d'achats")).toBeVisible();
  await expect(page.getByText("Dettes en cours et passées")).toHaveCount(0);
});
