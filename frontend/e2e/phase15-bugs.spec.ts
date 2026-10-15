import { expect, test, type Page } from "@playwright/test";

import {
  customerWithCredit,
  E2E,
  emptyMyDrafts,
  loginThroughUi,
  managerApi,
  stockedProduct,
} from "./fixtures";

/**
 * Les trois bugs du lot 0 de la phase 15, vus de l'écran. L'API e2e tourne **sans** relais
 * ni worker : c'est exactement la situation où le CA du jour ne bougeait pas (B1).
 */
test.describe.configure({ timeout: 90_000 });

async function login(page: Page) {
  await page.goto("/login");
  await loginThroughUi(page, E2E);
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
}

/** Montant affiché par la tuile « Vendu aujourd'hui », en francs entiers. */
async function revenueToday(page: Page): Promise<number> {
  const figure = page
    .getByRole("link", { name: /^Vendu aujourd'hui/ })
    .first()
    .locator(".numeric");
  await expect(figure).toBeVisible({ timeout: 30_000 });
  return Number((await figure.innerText()).replace(/\D/g, ""));
}

test("B1 — une vente fait monter « Vendu aujourd'hui » sans worker ni relais", async ({
  page,
  request,
}) => {
  const client = await managerApi(request);
  const product = await stockedProduct(client, { stock: "10", price: "1500" });
  await emptyMyDrafts(request);
  await login(page);
  const before = await revenueToday(page);

  await page.goto("/sales/new");
  await page.getByRole("searchbox", { name: "Chercher un article" }).fill(product.name);
  await page.getByRole("button", { name: `Ajouter ${product.name}` }).click();
  const qty = page.getByRole("textbox", { name: `Quantité de ${product.name}` });
  await qty.fill("2");
  await qty.press("Enter");
  await expect(page.getByRole("button", { name: /^Encaisser 3\s000\sF$/ })).toBeEnabled();
  await page.getByRole("button", { name: /^Encaisser/ }).click();
  await expect(page.getByRole("heading", { name: "Vente enregistrée" })).toBeVisible();

  await page.goto("/dashboard");
  await expect.poll(() => revenueToday(page)).toBe(before + 3000);
});

test("B2 — une dette encaissée fait passer la vente à « Payé »", async ({ page, request }) => {
  const client = await managerApi(request);
  const product = await stockedProduct(client, { stock: "10" });
  const customer = await customerWithCredit(client);
  const sale = await client.post("/sales", { customer_id: customer.id });
  await client.post(`/sales/${sale.id}/items`, { product_id: product.id, qty: "2" });
  await client.post(`/sales/${sale.id}/confirm`, { paid_amount: "0", method: "cash" });

  await login(page);
  await page.goto(`/sales?search=${encodeURIComponent(sale.sale_no)}`);
  await expect(page.getByRole("link", { name: new RegExp(customer.name) })).toContainText(
    /Reste\s2\s000\sF/,
  );

  await page.goto("/finance/debts?party=customer&status=open&page_size=100");
  await page
    .getByRole("main")
    .getByRole("listitem")
    .filter({ hasText: customer.name })
    .first()
    .getByRole("button", { name: "Régler" })
    .click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Combien il paie ?").fill("2000");
  await dialog.getByRole("button", { name: "Encaisser" }).click();
  await expect(page.getByText("Dette encaissée.")).toBeVisible();

  await page.goto(`/sales?search=${encodeURIComponent(sale.sale_no)}`);
  const row = page.getByRole("link", { name: new RegExp(customer.name) });
  await expect(row).toContainText("Payé");
  await expect(row).not.toContainText("Reste");
});

test("B3 — avec 30 clients, le 30ᵉ se trouve en défilant et se choisit", async ({
  page,
  request,
}) => {
  const client = await managerApi(request);
  // « Zz » : en fin d'ordre alphabétique, après les clients des autres parcours.
  const prefix = `Zz Défilement ${crypto.randomUUID().slice(0, 6)}`;
  for (let index = 1; index <= 30; index += 1) {
    await client.post("/customers", { name: `${prefix} ${String(index).padStart(2, "0")}` });
  }
  const last = `${prefix} 30`;

  await login(page);
  await page.goto("/sales/new");
  await page.getByRole("button", { name: /Client de passage.*Changer/ }).click();
  await page.getByRole("combobox", { name: "Rechercher un client (nom ou code)" }).click();
  const list = page.getByRole("listbox");
  await expect(list.getByRole("option").first()).toContainText("Client de passage");

  // La liste n'est pas rognée : elle déborde de la carte « Client ».
  const target = list.getByRole("option", { name: new RegExp(last) });
  for (let attempt = 0; attempt < 20 && !(await target.isVisible()); attempt += 1) {
    await list.evaluate((element) => element.scrollTo(0, element.scrollHeight));
    await page.waitForTimeout(250);
  }
  await target.scrollIntoViewIfNeeded();
  await expect(target).toBeInViewport();
  await target.click();

  await expect(page.getByRole("button", { name: new RegExp(last) })).toBeVisible();
  await expect(list).toBeHidden();
});
