import { expect, test, type Page } from "@playwright/test";

import { customerWithCredit, E2E, loginThroughUi, managerApi, stockedProduct } from "./fixtures";

const CAPTURES = "../docs/design/captures/phase-12";

// Parcours longs, et le serveur de développement compile chaque page à la première visite.
test.describe.configure({ timeout: 60_000 });

/** Montant tel que l'écran l'affiche (« 3 000 FCFA »), séparateurs compris. */
const amount = (digits: string) => new RegExp(`${digits.replace(/ /g, "\\s")}\\sFCFA`);

async function login(page: Page) {
  await page.goto("/login");
  await loginThroughUi(page, E2E);
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
}

async function addArticle(page: Page, name: string) {
  const search = page.getByRole("combobox", { name: "Ajouter un article (nom ou SKU)" });
  await search.fill(name);
  await page.getByRole("option", { name: new RegExp(name) }).click();
  await expect(page.getByRole("textbox", { name: `Quantité de ${name}` })).toBeVisible();
}

async function setQty(page: Page, name: string, qty: string) {
  const input = page.getByRole("textbox", { name: `Quantité de ${name}` });
  await input.fill(qty);
  await input.press("Enter");
  await expect(page.getByText("Totaux calculés par le serveur")).toBeVisible();
}

test("brouillon, confirmation avec paiement partiel, puis reçu", async ({ page, request }) => {
  const client = await managerApi(request);
  const product = await stockedProduct(client, { stock: "10" });
  const customer = await customerWithCredit(client);
  await login(page);

  await page.goto("/sales/new");
  await page
    .getByRole("combobox", { name: "Rechercher un client (nom ou code)" })
    .fill(customer.name);
  await page.getByRole("option", { name: new RegExp(customer.name) }).click();
  await expect(page.getByText(customer.name)).toBeVisible();

  await addArticle(page, product.name);
  // Le brouillon existe côté serveur dès le premier article : l'URL le désigne.
  await expect(page).toHaveURL(/\/sales\/[0-9a-f-]+\/edit$/);
  await setQty(page, product.name, "3");
  await expect(page.getByText(amount("3 000")).first()).toBeVisible();
  await page.screenshot({
    path: `${CAPTURES}/nouvelle-vente.png`,
    fullPage: true,
    animations: "disabled",
  });

  // Le brouillon survit à un rechargement.
  await page.reload();
  await expect(page.getByRole("textbox", { name: `Quantité de ${product.name}` })).toHaveValue("3");

  await page.getByRole("radio", { name: "Une partie" }).click();
  await page.getByLabel("Il donne maintenant").fill("1000");
  await expect(page.getByText(/Il restera 2\s000\sF à payer/)).toBeVisible();
  await page.getByRole("button", { name: "Confirmer la vente" }).click();

  await expect(page).toHaveURL(/\/sales\/[0-9a-f-]+$/);
  await expect(page.getByText("Confirmée", { exact: true })).toBeVisible();
  await expect(page.getByText("Dette liée")).toBeVisible();
  const due = page
    .locator("div")
    .filter({ hasText: /^Reste dû/ })
    .first();
  await expect(due).toContainText(amount("2 000"));
  await page.screenshot({
    path: `${CAPTURES}/detail-vente.png`,
    fullPage: true,
    animations: "disabled",
  });

  await page.getByRole("link", { name: "Reçu" }).click();
  await expect(page.getByRole("article")).toContainText(product.name);
  await expect(page.getByRole("article")).toContainText(amount("1 000"));
  await page.screenshot({
    path: `${CAPTURES}/recu-ticket.png`,
    fullPage: true,
    animations: "disabled",
  });
  await page.getByRole("radio", { name: "A4" }).click();
  await expect(page).toHaveURL(/format=a4/);
  await page.screenshot({
    path: `${CAPTURES}/recu-a4.png`,
    fullPage: true,
    animations: "disabled",
  });
});

test("une vente au-delà du stock est bloquée avec le bon message", async ({ page, request }) => {
  const client = await managerApi(request);
  const product = await stockedProduct(client, { stock: "2" });
  await login(page);

  await page.goto("/sales/new");
  await addArticle(page, product.name);
  await setQty(page, product.name, "5");

  // Confort : l'aperçu du stock bloque la confirmation avant tout envoi.
  await expect(page.getByText("Stock insuffisant — 2 disponible(s)")).toBeVisible();
  const confirm = page.getByRole("button", { name: "Confirmer la vente" });
  await expect(confirm).toBeDisabled();
  await page.screenshot({
    path: `${CAPTURES}/stock-insuffisant.png`,
    fullPage: true,
    animations: "disabled",
  });

  // Vérité serveur : le stock baisse ailleurs après l'aperçu, et c'est la base qui refuse.
  await setQty(page, product.name, "2");
  await expect(confirm).toBeEnabled();
  await client.post("/inventory/movements", {
    product_id: product.id,
    // Une perte porte sa raison en liste fermée (ADR 0067).
    reason_code: "damaged",
    qty_delta: "-1",
  });
  await confirm.click();
  await expect(page.getByText("Stock insuffisant — 1 disponible(s)")).toBeVisible();
  await expect(page).toHaveURL(/\/edit$/);
});

test("retour partiel puis remboursement", async ({ page, request }) => {
  const client = await managerApi(request);
  const product = await stockedProduct(client, { stock: "10" });
  const sale = await client.post("/sales", {});
  await client.post(`/sales/${sale.id}/items`, { product_id: product.id, qty: "4", discount: "0" });
  await client.post(`/sales/${sale.id}/confirm`, { paid_amount: "4000", method: "cash" });
  await login(page);

  await page.goto(`/sales/${sale.id}`);
  await page.getByRole("link", { name: "Effectuer un retour" }).click();
  await page.getByRole("textbox", { name: `Quantité retournée de ${product.name}` }).fill("1");
  await page.getByLabel("Motif (facultatif)").fill("Emballage abîmé");
  await page.screenshot({
    path: `${CAPTURES}/retour-saisie.png`,
    fullPage: true,
    animations: "disabled",
  });
  await page.getByRole("button", { name: "Enregistrer le retour" }).click();

  await expect(page).toHaveURL(/\/sales\/returns\/[0-9a-f-]+$/);
  await expect(page.getByText("À régler", { exact: true })).toBeVisible();
  const due = page
    .locator("div")
    .filter({ hasText: /^Reste à régler/ })
    .first();
  await expect(due).toContainText(amount("1 000"));

  // Remboursement en deux fois : 400 puis le reste.
  await page.getByLabel("Combien vous rendez ?").fill("400");
  await page.getByRole("button", { name: "Enregistrer le règlement" }).click();
  await expect(page.getByText("Partiellement réglé", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Combien vous rendez ?")).toHaveValue("600");
  await page.getByRole("button", { name: "Enregistrer le règlement" }).click();
  await expect(page.getByText("Réglé", { exact: true })).toBeVisible();
  await page.screenshot({
    path: `${CAPTURES}/retour-regle.png`,
    fullPage: true,
    animations: "disabled",
  });

  // La vente porte désormais le badge dérivé « Retournée ».
  await page.goto(`/sales/${sale.id}`);
  await expect(page.getByText("Retournée", { exact: true })).toBeVisible();
});
