import { expect, test, type Page } from "@playwright/test";

import {
  createSalesperson,
  customerWithCredit,
  E2E,
  emptyMyDrafts,
  loginThroughUi,
  managerApi,
  stockedProduct,
  type Credentials,
} from "./fixtures";

/**
 * Brouillons (prompt 29, P1, ADR 0101) : une saisie commencée se retrouve ailleurs dans
 * l'application et après un rechargement ; elle disparaît à l'envoi et à la déconnexion ;
 * personne d'autre ne la voit ; aucun mot de passe n'est jamais gardé.
 */
test.describe.configure({ timeout: 120_000, mode: "serial" });

const RESTORED = "Brouillon retrouvé : votre saisie était gardée.";
const MAIN_MENU = "Menu principal";
const NAME = "Nom du client";

async function login(page: Page, credentials: Credentials = E2E) {
  await page.context().clearCookies();
  await page.goto("/login");
  await loginThroughUi(page, credentials);
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
}

/** Tout ce que l'appareil garde, pour y chercher une valeur. */
async function stored(page: Page): Promise<string> {
  return page.evaluate(() => JSON.stringify({ ...window.localStorage, ...window.sessionStorage }));
}

async function drafts(page: Page): Promise<string[]> {
  return page.evaluate(() =>
    Object.keys(window.localStorage).filter((key) => key.startsWith("coges:draft:")),
  );
}

async function typeAmount(page: Page, digits: string[]) {
  for (const key of digits) await page.getByRole("button", { name: key, exact: true }).click();
}

test.beforeEach(async ({ request }) => {
  await emptyMyDrafts(request);
});

test("dépense : retrouvée après un autre onglet et un rechargement, effacée à l'envoi", async ({
  page,
  request,
}) => {
  const client = await managerApi(request);
  const category = await client.post("/expense-categories", {
    name: `Eau ${crypto.randomUUID().slice(0, 6)}`,
    kind: "variable",
  });
  await login(page);

  await page.goto("/finance/expenses");
  await page.getByRole("radio", { name: category.name }).click();
  await typeAmount(page, ["4", "5", "0", "0"]);
  // Autre onglet de l'application, puis retour.
  await page
    .getByRole("navigation", { name: MAIN_MENU })
    .getByRole("link", { name: "Vendre" })
    .click();
  await expect(page).toHaveURL(/\/sales\/new$/);
  await page.goto("/finance/expenses");
  await expect(page.getByText(RESTORED)).toBeVisible();
  await expect(page.getByRole("radio", { name: category.name })).toBeChecked();
  await expect(page.getByRole("textbox", { name: "Combien ?" })).toHaveValue("4500");

  // Rechargement : toujours là.
  await page.reload();
  await expect(page.getByText(RESTORED)).toBeVisible();

  await page.getByRole("button", { name: "Enregistrer la dépense" }).click();
  await expect(
    page.getByText(new RegExp(`^${category.name} : 4\\s500\\sF enregistrés\\.$`)),
  ).toBeVisible();
  await expect.poll(() => drafts(page)).toEqual([]);
  await page.reload();
  await expect(page.getByText(RESTORED)).toHaveCount(0);
});

test("déconnexion : les brouillons disparaissent ; une autre personne ne voit rien", async ({
  page,
  request,
}) => {
  const client = await managerApi(request);
  const category = await client.post("/expense-categories", {
    name: `Gaz ${crypto.randomUUID().slice(0, 6)}`,
    kind: "variable",
  });
  const seller = await createSalesperson(request);
  await login(page);

  // Une saisie laissée, puis la session perdue sans se déconnecter (navigateur partagé).
  await page.goto("/finance/expenses");
  await page.getByRole("radio", { name: category.name }).click();
  await typeAmount(page, ["7", "0", "0"]);
  await page.goto("/customers/new");
  await page.getByLabel(NAME, { exact: true }).fill("Brouillon du gérant");
  await expect.poll(async () => (await drafts(page)).length).toBe(2);
  await login(page, seller);
  await page.goto("/customers/new");
  await expect(page.getByLabel(NAME, { exact: true })).toBeVisible();
  await expect(page.getByText(RESTORED)).toHaveCount(0);
  await expect(page.getByLabel(NAME, { exact: true })).toHaveValue("");

  // Le gérant revient, retrouve sa saisie, puis se déconnecte : tout disparaît.
  await login(page);
  await page.goto("/finance/expenses");
  await expect(page.getByText(RESTORED)).toBeVisible();
  await page.getByRole("button", { name: "Réglages et compte" }).click();
  await page.getByRole("menuitem", { name: "Se déconnecter" }).click();
  await expect(page).toHaveURL(/\/login/);
  const left = await page.evaluate(() =>
    Object.keys(window.localStorage).filter((key) => key.startsWith("coges:draft:")),
  );
  // Seuls ceux du vendeur, qui ne s'est pas déconnecté, pourraient rester : il n'en a pas.
  expect(left).toEqual([]);
});

test("un mot de passe tapé n'est jamais gardé sur l'appareil", async ({ page }) => {
  const trap = "piege-mot-de-passe-2026";
  await page.goto("/login");
  await page.getByLabel("Mot de passe", { exact: true }).fill(trap);
  await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
  expect(await stored(page)).not.toContain(trap);

  await login(page);
  await page.goto("/account/password");
  await page.getByLabel("Mot de passe actuel", { exact: true }).fill(trap);
  await page.getByLabel("Nouveau mot de passe", { exact: true }).fill(`${trap}-nouveau`);
  await page.goto("/settings/people");
  await page.waitForTimeout(600);
  expect(await stored(page)).not.toContain(trap);
});

test("vente à moitié encaissée : retrouvée au retour, une seule vente à la fin", async ({
  page,
  request,
}) => {
  const client = await managerApi(request);
  const product = await stockedProduct(client, { stock: "10" });
  const customer = await client.post("/customers", {
    name: `Client brouillon ${crypto.randomUUID().slice(0, 6)}`,
    credit_limit: "1000000",
  });
  await login(page);

  await page.goto("/sales/new");
  await page.getByRole("button", { name: /Client de passage.*Changer/ }).click();
  await page
    .getByRole("combobox", { name: "Rechercher un client (nom ou code)" })
    .fill(customer.name);
  await page.getByRole("option", { name: new RegExp(customer.name) }).click();
  await page.getByRole("searchbox", { name: "Chercher un article" }).fill(product.name);
  await page.getByRole("button", { name: `Ajouter ${product.name}` }).click();
  await expect(page).toHaveURL(/\/sales\/[0-9a-f-]+\/edit$/);
  await page.getByRole("button", { name: "Une partie", exact: true }).click();
  await typeAmount(page, ["4", "0", "0"]);
  await page.waitForLoadState("networkidle");

  // Ailleurs, puis retour par « Vendre » : l'écran gardé par Next revient tel quel.
  await page
    .getByRole("navigation", { name: MAIN_MENU })
    .getByRole("link", { name: "Clients" })
    .click();
  await page
    .getByRole("navigation", { name: MAIN_MENU })
    .getByRole("link", { name: "Vendre" })
    .click();
  const partial = page.getByRole("button", { name: "Une partie", exact: true });
  await expect(partial).toHaveAttribute("aria-pressed", "true");
  // Rechargement (ou page déchargée par le téléphone) : le brouillon est retrouvé.
  await page.reload();
  await expect(page.getByText(RESTORED)).toBeVisible();
  await expect(partial).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: /^Encaisser 400\sF$/ }).click();
  await expect(page.getByRole("heading", { name: "Vente enregistrée" })).toBeVisible();
  // La clé renouvelée après l'envoi ne recrée pas le brouillon, même après l'écriture différée.
  await page.waitForTimeout(1_000);
  expect(await drafts(page)).toEqual([]);
  await page.reload();
  await expect(page.getByRole("searchbox", { name: "Chercher un article" })).toBeVisible();
  await expect(page.getByText(RESTORED)).toHaveCount(0);

  const sales = await client.get(`/sales?customer_id=${customer.id}&include_drafts=false`);
  expect(sales.items).toHaveLength(1);
});

test("retour partiel au remboursement lent : rien n'est retrouvé, aucun second retour", async ({
  page,
  request,
}) => {
  const client = await managerApi(request);
  const product = await stockedProduct(client, { stock: "20" });
  const customer = await customerWithCredit(client);
  const draft = await client.post("/sales", { customer_id: customer.id });
  await client.post(`/sales/${draft.id}/items`, {
    product_id: product.id,
    qty: "4",
    discount: "0",
  });
  await client.post(`/sales/${draft.id}/confirm`, { paid_amount: "4000", method: "cash" });
  await login(page);

  // Le remboursement prend bien plus que l'écriture différée (400 ms).
  await page.route("**/api/v1/sale-returns/*/refunds", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1_500));
    await route.continue();
  });
  await page.goto(`/sales/${draft.id}/returns/new`);
  const qty = page.getByRole("textbox", { name: `Quantité rendue de ${product.name}` });
  await qty.fill("2");
  await expect.poll(async () => (await drafts(page)).length).toBe(1);
  await page.getByRole("button", { name: "Enregistrer le retour" }).click();
  await expect(page.getByRole("heading", { name: "Retour enregistré" })).toBeVisible({
    timeout: 15_000,
  });
  await page.waitForTimeout(1_000);
  expect(await drafts(page)).toEqual([]);

  await page.reload();
  await expect(qty).toBeVisible();
  await expect(page.getByText(RESTORED)).toHaveCount(0);
  await expect(qty).toHaveValue("");
  const detail = await client.get(`/sales/${draft.id}`);
  expect(detail.items[0].returned_qty).toBe("2.000");
});

test("session refusée à la réouverture : les brouillons disparaissent", async ({
  page,
  request,
}) => {
  const client = await managerApi(request);
  const category = await client.post("/expense-categories", {
    name: `Sel ${crypto.randomUUID().slice(0, 6)}`,
    kind: "variable",
  });
  await login(page);
  await page.goto("/finance/expenses");
  await page.getByRole("radio", { name: category.name }).click();
  await typeAmount(page, ["3", "0", "0"]);
  await expect.poll(async () => (await drafts(page)).length).toBe(1);

  // Application rouverte : le jeton en mémoire est perdu et le serveur refuse le refresh,
  // avant que l'identité de la personne soit relue.
  await page.route("**/api/v1/auth/refresh", (route) =>
    route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({
        error: { code: "invalid_refresh_token", message: "Session expirée.", details: {} },
      }),
    }),
  );
  await page.reload();
  await expect(page).toHaveURL(/\/login\?reason=expired/, { timeout: 15_000 });
  await expect.poll(() => drafts(page)).toEqual([]);
  expect(await page.evaluate(() => window.localStorage.getItem("coges:draft-owner"))).toBeNull();
});

test("déconnexion depuis un autre onglet : le brouillon n'est pas réécrit", async ({
  page,
  request,
}) => {
  const client = await managerApi(request);
  const category = await client.post("/expense-categories", {
    name: `Thé ${crypto.randomUUID().slice(0, 6)}`,
    kind: "variable",
  });
  await login(page);
  const other = await page.context().newPage();
  await other.goto("/finance/expenses");
  await other.getByRole("radio", { name: category.name }).click();
  await typeAmount(other, ["9", "0", "0"]);
  await expect.poll(async () => (await drafts(other)).length).toBe(1);

  await page.getByRole("button", { name: "Réglages et compte" }).click();
  await page.getByRole("menuitem", { name: "Se déconnecter" }).click();
  await expect(page).toHaveURL(/\/login/);
  await expect(other).toHaveURL(/\/login/, { timeout: 15_000 });
  await other.waitForTimeout(1_000);
  expect(await drafts(other)).toEqual([]);
  await other.close();
});
