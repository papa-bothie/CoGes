import { expect, test, type Page } from "@playwright/test";

import {
  customerWithCredit,
  E2E,
  emptyMyDrafts,
  loginThroughUi,
  managerApi,
  stockedProduct,
} from "./fixtures";

const CAPTURES = "../docs/design/captures/phase-12";

// Parcours longs, et le serveur de développement compile chaque page à la première visite.
// En série : « Nouvelle vente » reprend le brouillon du jour du même gérant.
test.describe.configure({ timeout: 60_000, mode: "serial" });

test.beforeEach(async ({ request }) => {
  await emptyMyDrafts(request);
});

/** Montant tel que la maquette v2 l'affiche (« 3 000 F »), séparateurs compris. */
const amount = (digits: string) => new RegExp(`${digits.replace(/ /g, "\\s")}\\sF`);

async function login(page: Page) {
  await page.goto("/login");
  await loginThroughUi(page, E2E);
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
}

/** Cherche l'article dans la grille de « Nouvelle vente » et touche sa tuile (maquette 02). */
async function addArticle(page: Page, name: string) {
  await page.getByRole("searchbox", { name: "Chercher un article" }).fill(name);
  const tile = page.getByRole("button", { name: `Ajouter ${name}` });
  await expect(tile).toHaveCount(1);
  await tile.click();
  await expect(page.getByRole("textbox", { name: `Quantité de ${name}` })).toBeVisible();
}

async function setQty(page: Page, name: string, qty: string) {
  const input = page.getByRole("textbox", { name: `Quantité de ${name}` });
  await input.fill(qty);
  await input.press("Enter");
  await expect(input).toHaveValue(qty);
  await page.waitForLoadState("networkidle");
}

test("brouillon, confirmation avec paiement partiel, puis reçu", async ({ page, request }) => {
  const client = await managerApi(request);
  const product = await stockedProduct(client, { stock: "10" });
  const customer = await customerWithCredit(client);
  await login(page);

  await page.goto("/sales/new");
  await page.getByRole("button", { name: /Client de passage.*Changer/ }).click();
  await page
    .getByRole("combobox", { name: "Rechercher un client (nom ou code)" })
    .fill(customer.name);
  await page.getByRole("option", { name: new RegExp(customer.name) }).click();
  await expect(page.getByRole("button", { name: new RegExp(customer.name) })).toBeVisible();

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

  await page.getByRole("button", { name: "Une partie", exact: true }).click();
  await page.getByLabel("Il donne maintenant").fill("1000");
  await expect(page.getByText(/Il restera 2\s000\sF à payer/)).toBeVisible();
  await page.getByRole("button", { name: /^Encaisser 1\s000\sF$/ }).click();

  // Écran de succès, puis le détail de la vente.
  await expect(page.getByRole("heading", { name: "Vente enregistrée" })).toBeVisible();
  await expect(
    page.getByText(new RegExp(`${customer.name} doit encore 2\\s000\\sF`)),
  ).toBeVisible();
  await page.getByRole("link", { name: "Imprimer le reçu" }).click();
  await expect(page.getByRole("article")).toContainText(product.name);
  await expect(page.getByRole("article")).toContainText(amount("1 000"));
  await page.screenshot({
    path: `${CAPTURES}/recu-ticket.png`,
    fullPage: true,
    animations: "disabled",
  });
  await page.getByRole("button", { name: "Facture A4" }).click();
  await expect(page).toHaveURL(/format=a4/);
  await expect(page.getByRole("article")).toContainText("trois mille francs CFA");

  await page.getByRole("link", { name: "Retour à la vente" }).click();
  await expect(page.getByText("Reste 2 000 F").first()).toBeVisible();
  await expect(page.getByText("Reste à payer")).toBeVisible();
  await page.screenshot({
    path: `${CAPTURES}/detail-vente.png`,
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
  const confirm = page.getByRole("button", { name: /^Encaisser/ });
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

test("retour partiel rendu en espèces, puis le reste réglé sur la fiche", async ({
  page,
  request,
}) => {
  const client = await managerApi(request);
  const product = await stockedProduct(client, { stock: "10" });
  const sale = await client.post("/sales", {});
  await client.post(`/sales/${sale.id}/items`, { product_id: product.id, qty: "4", discount: "0" });
  await client.post(`/sales/${sale.id}/confirm`, { paid_amount: "4000", method: "cash" });
  await login(page);

  await page.goto(`/sales/${sale.id}`);
  await page.getByRole("link", { name: "Retour d'articles" }).click();
  await page.getByRole("textbox", { name: `Quantité rendue de ${product.name}` }).fill("1");
  await expect(page.getByText(amount("1 000")).first()).toBeVisible();
  await page.getByRole("button", { name: "Pas le bon article" }).click();
  // Pas de dette sur cette vente : on rend l'argent, 400 F seulement pour l'instant.
  await page.getByRole("button", { name: /Lui rendre de l’argent/ }).click();
  await page.getByLabel("Combien vous lui rendez ?").fill("400");
  await page.screenshot({
    path: `${CAPTURES}/retour-saisie.png`,
    fullPage: true,
    animations: "disabled",
  });
  await page.getByRole("button", { name: "Enregistrer le retour" }).click();
  await expect(page.getByRole("heading", { name: "Retour enregistré" })).toBeVisible();
  await expect(page.getByText(/400\sF rendus à Client de passage/)).toBeVisible();

  // Le bon de retour reprend le gabarit du ticket.
  await page.getByRole("link", { name: "Imprimer le bon de retour" }).click();
  await expect(page.getByRole("article")).toContainText("BON DE RETOUR");
  await expect(page.getByRole("article")).toContainText("RESTE À RENDRE");

  // Le reste se règle sur la fiche du retour, comme avant.
  await page.goto(`/sales/${sale.id}`);
  await page.getByRole("link", { name: /Retour n° \d+/ }).click();
  await expect(page.getByLabel("Combien vous rendez ?")).toHaveValue("600");
  await page.getByRole("button", { name: "Enregistrer le règlement" }).click();
  await expect(page.getByText("Réglé", { exact: true })).toBeVisible();
  await page.screenshot({
    path: `${CAPTURES}/retour-regle.png`,
    fullPage: true,
    animations: "disabled",
  });

  // La vente porte la pastille « Retour ».
  await page.goto(`/sales/${sale.id}`);
  await expect(page.getByText(/Retour : 1\s000\sF/).first()).toBeVisible();
});

test("annuler une vente demande la raison en boutons", async ({ page, request }) => {
  const client = await managerApi(request);
  const product = await stockedProduct(client, { stock: "5" });
  const customer = await customerWithCredit(client);
  const sale = await client.post("/sales", { customer_id: customer.id });
  await client.post(`/sales/${sale.id}/items`, { product_id: product.id, qty: "1", discount: "0" });
  await client.post(`/sales/${sale.id}/confirm`, { paid_amount: "0", method: "cash" });
  await login(page);

  await page.goto(`/sales/${sale.id}`);
  await page.getByRole("button", { name: "Annuler la vente" }).click();
  const yes = page.getByRole("button", { name: "Oui, annuler la vente" });
  await expect(yes).toBeDisabled();
  await page.getByRole("button", { name: "Vente enregistrée deux fois" }).click();
  await yes.click();
  await expect(
    page.getByText(
      "Vente annulée (vente enregistrée deux fois). Les articles reviennent dans le stock.",
    ),
  ).toBeVisible();
  await expect(page.getByText("Annulée", { exact: true })).toBeVisible();
});
