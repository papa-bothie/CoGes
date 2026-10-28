import { expect, test, type Page } from "@playwright/test";

import {
  createSalesperson,
  customerWithCredit,
  E2E,
  loginThroughUi,
  managerApi,
  stockedProduct,
  type Credentials,
  type ManagerApi,
} from "./fixtures";

/**
 * Retours sur le terrain (prompt 28, C1, ADR 0097) : une vente confirmée se retourne,
 * qu'elle soit payée, payée en partie ou à crédit ; la dette restante est déduite
 * d'abord, le reste se rend dans le même écran ; le vendeur enregistre le retour et le
 * gérant rembourse. Le bouton « Retour » est sur la fiche **et** dans l'historique.
 */
test.describe.configure({ timeout: 90_000, mode: "serial" });

const amount = (digits: string) => new RegExp(`${digits.replace(/ /g, "\\s")}\\sF`);

async function login(page: Page, credentials: Credentials = E2E) {
  await page.goto("/login");
  await loginThroughUi(page, credentials);
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
}

/** Vente confirmée de `qty` articles à 1 000 F, payée à hauteur de `paid`. */
async function sale(client: ManagerApi, { qty, paid }: { qty: string; paid: string }) {
  const product = await stockedProduct(client, { stock: "20" });
  const customer = await customerWithCredit(client);
  const draft = await client.post("/sales", { customer_id: customer.id });
  await client.post(`/sales/${draft.id}/items`, { product_id: product.id, qty, discount: "0" });
  const confirmed = await client.post(`/sales/${draft.id}/confirm`, {
    paid_amount: paid,
    method: "cash",
  });
  return { id: draft.id as string, no: confirmed.sale_no as string, product, customer };
}

async function returnQty(page: Page, productName: string, qty: string) {
  await page.getByRole("textbox", { name: `Quantité rendue de ${productName}` }).fill(qty);
}

test("vente payée en totalité : retour depuis l'historique, argent rendu", async ({
  page,
  request,
}) => {
  const client = await managerApi(request);
  const paid = await sale(client, { qty: "4", paid: "4000" });
  await login(page);

  await page.goto("/sales?period=today");
  const number = paid.no.replace(/^V-0*/, "");
  await page.getByRole("link", { name: `Retour d'articles sur la vente n° ${number}` }).click();
  await expect(page.getByRole("heading", { name: "Retour d'articles" })).toBeVisible();
  await returnQty(page, paid.product.name, "2");
  await page.getByRole("button", { name: "Orange Money", exact: true }).click();
  await page.getByRole("button", { name: "Enregistrer le retour" }).click();
  await expect(page.getByRole("heading", { name: "Retour enregistré" })).toBeVisible();
  await expect(page.getByRole("status")).toContainText(amount("2 000"));
  await expect(page.getByRole("status")).toContainText("rendus à");

  const after = await client.get(`/inventory/stock?product_id=${paid.product.id}`);
  expect(after.items[0].qty_on_hand).toBe("18.000");
});

test("vente payée en partie : la dette baisse d'abord, le reste se rend dans le même écran", async ({
  page,
  request,
}) => {
  const client = await managerApi(request);
  // 10 000 F, 4 000 F payés : 6 000 F de dette. Retour de 8 articles = 8 000 F.
  const partial = await sale(client, { qty: "10", paid: "4000" });
  await login(page);

  await page.goto(`/sales/${partial.id}`);
  await page.getByRole("link", { name: "Retour d'articles" }).click();
  await returnQty(page, partial.product.name, "8");
  await expect(page.getByText(/6\s000\sF sont déduits de sa dette/)).toBeVisible();
  await expect(page.getByText(/Reste à lui rendre : 2\s000\sF/)).toBeVisible();
  await expect(page.getByLabel("Combien vous lui rendez ?")).toHaveValue("2000");
  await page.getByRole("button", { name: "Enregistrer le retour" }).click();
  await expect(page.getByRole("heading", { name: "Retour enregistré" })).toBeVisible();
  await expect(page.getByRole("status")).toContainText(/doit maintenant 0\sF/);
  await expect(page.getByRole("status")).toContainText(amount("2 000"));

  const detail = await client.get(`/sales/${partial.id}`);
  expect(detail.debt.balance).toBe("0.00");
  expect(detail.returnable).toBe(true);
});

test("vendeur : le retour s'enregistre, la dette baisse, le gérant rembourse le reste", async ({
  page,
  request,
}) => {
  const client = await managerApi(request);
  const seller = await createSalesperson(request);
  const paid = await sale(client, { qty: "3", paid: "3000" });
  const partial = await sale(client, { qty: "5", paid: "1000" });
  await login(page, seller);

  // Vente payée : rien n'est tenté, l'écran dit qui rembourse.
  await page.goto(`/sales/${paid.id}`);
  await page.getByRole("link", { name: "Retour d'articles" }).click();
  await returnQty(page, paid.product.name, "1");
  await expect(page.getByText(/Le gérant lui rendra 1\s000\sF/)).toBeVisible();
  await expect(page.getByRole("button", { name: /Lui rendre de l’argent/ })).toHaveCount(0);
  await page.getByRole("button", { name: "Enregistrer le retour" }).click();
  await expect(page.getByRole("heading", { name: "Retour enregistré" })).toBeVisible();
  await expect(page.getByRole("status")).toHaveText(/Le gérant doit encore rembourser 1\s000\sF/);

  // Vente à crédit en partie : la déduction de la dette se fait tout de suite.
  await page.goto(`/sales/${partial.id}`);
  await page.getByRole("link", { name: "Retour d'articles" }).click();
  await returnQty(page, partial.product.name, "2");
  await page.getByRole("button", { name: "Enregistrer le retour" }).click();
  await expect(page.getByRole("status")).toContainText(/doit maintenant 2\s000\sF/);
  expect((await client.get(`/sales/${partial.id}`)).debt.balance).toBe("2000.00");

  // Côté gérant, le premier retour attend son remboursement.
  const returns = await client.get(`/sales/${paid.id}/returns`);
  expect(returns.items[0].refund_status).toBe("pending");
  await page.context().clearCookies();
  await login(page);
  await page.goto(`/sales/${paid.id}`);
  await expect(page.getByText("À régler", { exact: true })).toBeVisible();
});
