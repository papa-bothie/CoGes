import { expect, test, type Locator, type Page } from "@playwright/test";

import {
  createSalesperson,
  customerWithCredit,
  E2E,
  loginThroughUi,
  managerApi,
  stockedProduct,
  type ManagerApi,
} from "./fixtures";

/**
 * L'argent, lot 3d (ADR 0073) : encaisser une dette, payer un fournisseur, ajouter une
 * dépense, annuler une ligne de caisse par une ligne inverse.
 */
test.describe.configure({ timeout: 90_000 });

async function login(page: Page, credentials = E2E) {
  await page.goto("/login");
  await loginThroughUi(page, credentials);
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
}

/** Vente à crédit de `qty` articles à 1 000 F, rien payé : une dette de qty × 1 000 F. */
async function creditSale(client: ManagerApi, customerId: string, qty: string) {
  const product = await stockedProduct(client, { stock: "50" });
  const sale = await client.post("/sales", { customer_id: customerId });
  await client.post(`/sales/${sale.id}/items`, { product_id: product.id, qty, discount: "0" });
  await client.post(`/sales/${sale.id}/confirm`, { paid_amount: "0", method: "cash" });
  return sale as { id: string; sale_no: string };
}

/** Compte les touches d'un parcours (critère de fin de phase : « ≤ 4 touches »). */
function counter() {
  let touches = 0;
  return {
    tap: async (target: Locator) => {
      touches += 1;
      await target.click();
    },
    get count() {
      return touches;
    },
  };
}

test("encaisser toute la dette d'un client en 4 touches ; ses achats passent à « Payé »", async ({
  page,
  request,
}) => {
  const client = await managerApi(request);
  const customer = await customerWithCredit(client);
  const sale = await creditSale(client, customer.id, "3");
  await login(page);

  await page.goto("/finance");
  const taps = counter();
  await taps.tap(page.getByRole("link", { name: "Encaisser une dette" }).first());
  await expect(page.getByRole("heading", { level: 1, name: "Encaisser une dette" })).toBeVisible();
  await taps.tap(page.getByRole("button", { name: new RegExp(customer.name) }));
  await expect(page.getByRole("heading", { level: 2, name: customer.name })).toBeVisible();
  await taps.tap(page.getByRole("button", { name: /^Tout : 3\s000\sF$/ }));
  await taps.tap(page.getByRole("button", { name: /^Encaisser 3\s000\sF$/ }));
  await expect(
    page.getByText(`${customer.name} ne doit plus rien. Ses achats sont marqués « Payé ».`),
  ).toBeVisible();
  expect(taps.count).toBeLessThanOrEqual(4);
  await expect(
    page.getByRole("region", { name: customer.name }).getByText("Payé", { exact: true }),
  ).toBeVisible();

  // La vente le dit aussi (ADR 0062).
  await page.goto(`/sales/${sale.id}`);
  await expect(page.getByText("Payé").first()).toBeVisible();
});

test("encaisser une partie tapée au pavé : il restera le reste", async ({ page, request }) => {
  const client = await managerApi(request);
  const customer = await customerWithCredit(client);
  await creditSale(client, customer.id, "10");
  await login(page);

  await page.goto(`/finance/collect?customer=${customer.id}`);
  await expect(page.getByRole("heading", { level: 2, name: customer.name })).toBeVisible();
  for (const key of ["7", "5", "0", "0"]) {
    await page.getByRole("button", { name: key, exact: true }).click();
  }
  await expect(page.getByText(/^Il restera 2\s500\sF à payer$/)).toBeVisible();
  await page.getByRole("button", { name: "Wave", exact: true }).click();
  await page.getByRole("button", { name: /^Encaisser 7\s500\sF$/ }).click();
  await expect(page.getByText(/^7\s500\sF reçus\. Il reste 2\s500\sF\.$/)).toBeVisible();
});

test("payer un fournisseur, puis ajouter une dépense et l'annuler dans la caisse", async ({
  page,
  request,
}) => {
  const client = await managerApi(request);
  const marker = crypto.randomUUID().slice(0, 6);
  const supplier = await client.post("/suppliers", { name: `Grossiste ${marker}` });
  await client.post("/debts", {
    party_type: "supplier",
    supplier_id: supplier.id,
    principal: "60000",
  });
  const category = await client.post("/expense-categories", {
    name: `Électricité ${marker}`,
    kind: "variable",
  });
  await login(page);

  // Écran 19 : la moitié, puis le bandeau.
  await page.goto(`/finance/pay?supplier=${supplier.id}`);
  await expect(page.getByRole("heading", { level: 2, name: supplier.name })).toBeVisible();
  await page.getByRole("button", { name: /^La moitié : 30\s000\sF$/ }).click();
  await page.getByRole("button", { name: /^Payer 30\s000\sF$/ }).click();
  await expect(page.getByText(/^30\s000\sF payés\. Il reste 30\s000\sF\.$/)).toBeVisible();

  // Écran 20 : le type, le montant, « Enregistrer la dépense ».
  await page.goto("/finance/expenses");
  await page.getByRole("radio", { name: category.name }).click();
  for (const key of ["3", "5", "000"]) {
    await page.getByRole("button", { name: key, exact: true }).click();
  }
  await page.getByRole("button", { name: "Enregistrer la dépense" }).click();
  await expect(
    page.getByText(new RegExp(`^${category.name} : 35\\s000\\sF enregistrés\\.$`)),
  ).toBeVisible();

  // Écran 21 : la ligne de la dépense, « Annuler », la raison, la ligne inverse.
  await page.goto("/finance/cash");
  const row = page.getByRole("listitem").filter({ hasText: `Dépense · ${category.name}` });
  await row.getByRole("button", { name: "Annuler", exact: true }).click();
  await row.getByRole("button", { name: "Saisi deux fois" }).click();
  await expect(
    page.getByText(`Annulation : Dépense · ${category.name} (saisi deux fois)`),
  ).toBeVisible();
  await expect(
    page
      .getByRole("listitem")
      .filter({ hasText: new RegExp(`^Dépense · ${category.name}`) })
      .getByText("Annulé", { exact: true }),
  ).toBeVisible();
});

test("le vendeur ne voit pas L'argent", async ({ page, request }) => {
  const seller = await createSalesperson(request);
  await login(page, seller);
  await expect(page.getByRole("link", { name: "Argent" })).toHaveCount(0);
});
