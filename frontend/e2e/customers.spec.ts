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

test("ajouter un client en deux champs ; sa fiche dit ce qu'il doit et le lui rappelle", async ({
  page,
  request,
}) => {
  const client = await managerApi(request);
  const marker = crypto.randomUUID().slice(0, 6);
  const name = `Boutique ${marker}`;
  await login(page);

  // Écran 15 : une page, « +221 » affiché, le numéro se groupe tout seul, puis le succès.
  await page.goto("/customers");
  await page.getByRole("main").getByRole("link", { name: "Nouveau client" }).click();
  await expect(page).toHaveURL(/\/customers\/new$/);
  await expect(page.getByRole("radio", { name: "Un client" })).toBeChecked();
  await expect(page.getByText("+221")).toBeVisible();
  await page.getByLabel("Nom du client").fill(name);
  await page.getByLabel("Téléphone").fill("770000000");
  await expect(page.getByLabel("Téléphone")).toHaveValue("77 000 00 00");
  await page.getByRole("button", { name: "Enregistrer le client" }).click();
  await expect(page.getByRole("heading", { name })).toBeVisible();
  await expect(page.getByText("Client ajouté : vous pouvez lui vendre à crédit")).toBeVisible();

  // La liste le trouve par son téléphone ; sa carte mène à sa fiche.
  await page.goto("/customers");
  await page.getByRole("searchbox", { name: "Chercher" }).fill("77 000 00");
  await expect(page).toHaveURL(/search=/);
  await page.getByRole("link", { name: new RegExp(name) }).click();
  await expect(page).toHaveURL(/\/customers\/[0-9a-f-]+$/);
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
  const customerId = page.url().split("/").pop()!;
  const sale = await creditSale(client, customerId);

  // Écran 14 : ce qu'il doit, ses achats, le rappel WhatsApp.
  await page.reload();
  await expect(page.getByText("Reste à payer")).toBeVisible();
  await expect(page.getByText(/^1\s500\sF$/)).toBeVisible();
  await expect(
    page.getByRole("link", { name: new RegExp(`Vente n° ${Number(sale.sale_no.slice(2))}\\b`) }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Lui rappeler sa dette" }).click();
  await expect(page.getByLabel("Message WhatsApp")).toHaveValue(
    new RegExp(`^Bonjour Boutique, c’est .+ Il reste 1\\s500\\sF à régler`),
  );
  await expect(page.getByRole("link", { name: "Ouvrir WhatsApp" })).toHaveAttribute(
    "href",
    /^https:\/\/wa\.me\/221770000000\?text=/,
  );
  await page.screenshot({
    path: `${CAPTURES}/fiche-client.png`,
    fullPage: true,
    animations: "disabled",
  });

  // « Encaisser sa dette » ouvre l'écran 18, ce client déjà choisi (ADR 0073).
  await page.getByRole("link", { name: "Encaisser sa dette" }).click();
  await expect(page).toHaveURL(
    new RegExp(`/finance/collect\\?customer=${customerId}&from=%2Fcustomers%2F${customerId}$`),
  );
  await expect(page.getByRole("heading", { level: 2, name })).toBeVisible();
  // Le retour ramène à la fiche d'où l'on vient, nommée (ADR 0082).
  await page.getByRole("link", { name, exact: true }).first().click();
  await expect(page).toHaveURL(new RegExp(`/customers/${customerId}$`));

  // « Lui vendre » : la vente s'ouvre avec ce client déjà choisi.
  await page.getByRole("link", { name: "Lui vendre" }).click();
  await expect(page.getByRole("button", { name: /Changer$/ })).toContainText(name, {
    timeout: 30_000,
  });

  // « Modifier » : la même page, puis retour à la fiche.
  await page.goto(`/customers/${customerId}/edit`);
  await page.getByLabel("Nom du client").fill(`${name} et fils`);
  await page.getByRole("button", { name: "Enregistrer le client" }).click();
  await expect(page.getByRole("heading", { level: 1, name: `${name} et fils` })).toBeVisible();
  await page.goto("/customers");
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
  await creditSale(client, customer.id);
  await login(page, await createSalesperson(request));
  await page.goto(`/customers/${customer.id}`);
  await expect(page.getByRole("tab", { name: "Ses achats" })).toBeVisible();
  await expect(page.getByText("Reste à payer")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Encaisser sa dette" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Lui rappeler sa dette" })).toHaveCount(0);
  await page.goto("/customers");
  await expect(page.getByRole("button", { name: "Qui me doivent" })).toHaveCount(0);
});
