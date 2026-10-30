import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { ADMIN, enterCode } from "./mfa";

/**
 * Accès support encadré (ADR 0092), de bout en bout, sur l'entreprise `support-e2e` créée
 * par `e2e.sh reset` : bris de glace dans l'administration, bandeau côté commerçant,
 * lecture de données réelles, écriture refusée, fermeture, puis les deux journaux.
 */
const SHOP = {
  slug: "support-e2e",
  email: "gerant@support-e2e.example.com",
  password: "demo-coges-2026",
};
const API = "http://localhost:8100/api/v1";
const MERCHANT = "http://localhost:3100";
const WHY = "Le gérant signale par téléphone un écart de stock sur le riz";

async function axe(page: Page): Promise<void> {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  expect(results.violations).toEqual([]);
}

/** Un article de la boutique, créé par son gérant : la donnée que le support doit lire. */
async function stockedArticle(request: APIRequestContext): Promise<string> {
  const login = await request.post(`${API}/auth/login`, {
    data: { company_slug: SHOP.slug, email: SHOP.email, password: SHOP.password },
  });
  expect(login.ok()).toBeTruthy();
  const headers = { Authorization: `Bearer ${(await login.json()).access_token}` };
  const name = `Riz du support ${crypto.randomUUID().slice(0, 6)}`;
  const product = await request.post(`${API}/products`, {
    headers: { ...headers, "Idempotency-Key": crypto.randomUUID() },
    data: { name, unit_price: "1000", default_tax_rate: "0", reorder_point: "1" },
  });
  expect(product.ok(), await product.text()).toBeTruthy();
  const movement = await request.post(`${API}/inventory/movements`, {
    headers: { ...headers, "Idempotency-Key": crypto.randomUUID() },
    data: {
      product_id: (await product.json()).id,
      type: "initial",
      qty_delta: "12",
      unit_cost: "600",
    },
  });
  expect(movement.ok(), await movement.text()).toBeTruthy();
  return name;
}

async function openShopInAdmin(page: Page): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("E-mail").fill(ADMIN.email);
  await page.getByLabel("Mot de passe", { exact: true }).fill(ADMIN.password);
  await page.getByRole("button", { name: "Se connecter" }).click();
  await enterCode(page);
  await expect(page.getByRole("heading", { name: "Tableau de bord" })).toBeVisible();
  await page.goto("/companies");
  await page.getByLabel("Nom ou code").fill(SHOP.slug);
  await page.getByRole("button", { name: "Chercher" }).click();
  await page.getByRole("link", { name: "Parcours support" }).click();
  await expect(page.getByRole("heading", { name: "Accès support", exact: true })).toBeVisible();
}

async function managerSignsIn(page: Page): Promise<void> {
  await page.goto(`${MERCHANT}/login`);
  await page.getByLabel("Code de la boutique").fill(SHOP.slug);
  await page.getByLabel("Votre e-mail ou téléphone").fill(SHOP.email);
  await page.getByLabel("Mot de passe", { exact: true }).fill(SHOP.password);
  await page.getByRole("button", { name: "Entrer" }).click();
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 60_000 });
}

const BANNER = /Accès support actif depuis .*, par l’équipe CoGes, jusqu’à /;

test("accès support : bris de glace, lecture seule, fermeture, deux journaux", async ({
  page,
  browser,
  request,
}) => {
  test.setTimeout(240_000);
  const article = await stockedArticle(request);

  // 1. Bris de glace dans l'administration : motif obligatoire, 2 h par défaut.
  await openShopInAdmin(page);
  const card = page.getByRole("region", { name: "Accès support" });
  await card.getByLabel("Pourquoi cet accès ?").fill(WHY);
  await expect(card.getByLabel("Durée")).toHaveValue("120");
  await card.getByRole("button", { name: "Ouvrir un accès support" }).click();
  await expect(card.getByRole("status")).toHaveText("Accès support ouvert. Le gérant est prévenu.");
  await expect(card).toContainText("Accès ouvert par vous");
  await expect(card).toContainText(`Motif : ${WHY}`);
  await axe(page);

  // 2. « Voir l'entreprise » : le front commerçant, en lecture seule, avec le bandeau.
  const [shop] = await Promise.all([
    page.waitForEvent("popup"),
    card.getByRole("button", { name: "Voir l'entreprise" }).click(),
  ]);
  await expect(shop).toHaveURL(`${MERCHANT}/dashboard`, { timeout: 60_000 });
  expect(shop.url()).not.toContain("token");
  await expect(shop.getByText(BANNER)).toBeVisible({ timeout: 30_000 });
  await expect(shop.getByText("Vous consultez cette boutique en lecture seule.")).toBeVisible();

  // 3. Des données réelles se lisent…
  await shop.goto(`${MERCHANT}/products`);
  await expect(shop.getByText(article)).toBeVisible({ timeout: 30_000 });
  await axe(shop);

  // … aucune ne s'écrit, même en appelant l'API directement avec le jeton de l'onglet.
  const write = await shop.evaluate(async () => {
    const stored = JSON.parse(sessionStorage.getItem("coges_support") ?? "{}") as {
      token?: string;
    };
    const response = await fetch("/api/v1/categories", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${stored.token}` },
      body: JSON.stringify({ name: "Rayon interdit" }),
    });
    return { status: response.status, body: await response.json() };
  });
  expect(write.status).toBe(403);
  expect(write.body.error.code).toBe("support_read_only");

  // 4. Le gérant, connecté de son côté, voit le même bandeau.
  const managerContext = await browser.newContext({ locale: "fr-FR", timezoneId: "Africa/Dakar" });
  const manager = await managerContext.newPage();
  await managerSignsIn(manager);
  await expect(manager.getByText(BANNER)).toBeVisible({ timeout: 30_000 });
  await expect(manager.getByText("Vous consultez cette boutique en lecture seule.")).toHaveCount(0);

  // 5. Fermeture avant l'heure : l'onglet du support s'arrête à sa requête suivante.
  await card.getByRole("button", { name: "Fermer l'accès" }).click();
  await expect(card.getByRole("status")).toHaveText("Accès support fermé.");
  await expect(card).toContainText("terminée le");
  await shop.reload();
  await expect(shop).toHaveURL(`${MERCHANT}/support/termine`, { timeout: 60_000 });
  await expect(shop.getByRole("heading", { name: "L’accès support est terminé" })).toBeVisible();

  // 6. Le bandeau disparaît chez le gérant ; son historique garde l'ouverture et la fermeture.
  await manager.reload();
  await expect(manager).toHaveURL(/\/dashboard$/);
  await expect(manager.getByRole("navigation").first()).toBeVisible({ timeout: 30_000 });
  await expect(manager.getByText(BANNER)).toHaveCount(0);
  await manager.goto(`${MERCHANT}/settings/history`);
  await expect(manager.getByText("L’équipe CoGes a fermé son accès support")).toBeVisible({
    timeout: 30_000,
  });
  await expect(
    manager.getByText(
      `L’équipe CoGes a ouvert un accès support, en lecture seule. Motif : « ${WHY} »`,
    ),
  ).toBeVisible();
  await managerContext.close();
});
