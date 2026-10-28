import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { E2E, loginThroughUi, managerApi, managerToken, type Credentials } from "./fixtures";

/**
 * Droits (prompt 28, C3, ADR 0099) : un compte ne voit et n'atteint que ce que son rôle
 * autorise. Menu, adresse directe et serveur disent la même chose ; une grille changée
 * par le gérant vaut dès la requête suivante.
 */
test.describe.configure({ timeout: 120_000, mode: "serial" });

const NO_ACCESS = "Vous n'avez pas accès à cette page";
const MAIN_MENU = "Menu principal";
const MENU = ["Accueil", "Vendre", "Stock", "Clients", "Argent"] as const;
/** Lignes du comptable par défaut (matrice de l'ADR 0007), rétablies à la fin. */
const ACCOUNTANT_DEFAULT = [
  "base",
  "see",
  "see_money",
  "collect_debt",
  "manage_money",
  "audit",
  "export",
];

async function roleId(request: APIRequestContext, name: string): Promise<string> {
  const headers = { Authorization: `Bearer ${await managerToken(request, E2E)}` };
  const roles = await (await request.get("/api/v1/roles?page_size=50", { headers })).json();
  return roles.items.find((item: { name: string }) => item.name === name).id as string;
}

async function account(request: APIRequestContext, role: string): Promise<Credentials> {
  const headers = { Authorization: `Bearer ${await managerToken(request, E2E)}` };
  const email = `droits-${Date.now()}-${Math.round(Math.random() * 1e6)}@${E2E.slug}.example.com`;
  const password = "droits-e2e-2026-ok";
  const created = await request.post("/api/v1/users", {
    headers,
    data: { email, full_name: "Compte droits", password, role_ids: [role] },
  });
  expect(created.status(), await created.text()).toBe(201);
  return { slug: E2E.slug, email, password };
}

async function login(page: Page, credentials: Credentials) {
  await page.context().clearCookies();
  await page.goto("/login");
  await loginThroughUi(page, credentials);
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
}

async function tokenOf(request: APIRequestContext, credentials: Credentials) {
  const response = await request.post("/api/v1/auth/login", {
    data: {
      company_slug: credentials.slug,
      email: credentials.email,
      password: credentials.password,
    },
  });
  expect(response.ok()).toBeTruthy();
  return { Authorization: `Bearer ${(await response.json()).access_token}` };
}

/** Les entrées du menu principal, dans l'ordre (barre du haut, écran large). */
async function menu(page: Page): Promise<string[]> {
  const nav = page.getByRole("navigation", { name: MAIN_MENU });
  // La coquille est posée quand l'Accueil est là (toute personne connectée l'a).
  await expect(nav.getByRole("link", { name: "Accueil", exact: true })).toBeVisible();
  const shown: string[] = [];
  for (const label of MENU) {
    if (await nav.getByRole("link", { name: label, exact: true }).count()) shown.push(label);
  }
  return shown;
}

async function denied(page: Page, path: string, forbiddenApi: string) {
  const calls: string[] = [];
  const listen = (request: { url: () => string }) => {
    if (new URL(request.url()).pathname === forbiddenApi) calls.push(request.url());
  };
  page.on("request", listen);
  await page.goto(path);
  await expect(page.getByRole("heading", { name: NO_ACCESS })).toBeVisible();
  await page.waitForLoadState("networkidle");
  page.off("request", listen);
  expect(calls, `${path} ne doit rien charger de ${forbiddenApi}`).toEqual([]);
}

test.afterAll(async ({ request }) => {
  // Le comptable de l'entreprise `e2e` retrouve sa grille par défaut.
  const client = await managerApi(request);
  await client.put(`/roles/${await roleId(request, "comptable")}/abilities`, {
    abilities: ACCOUNTANT_DEFAULT,
  });
});

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
});

test("gérant : les cinq entrées et chaque écran", async ({ page }) => {
  await login(page, E2E);
  expect(await menu(page)).toEqual([...MENU]);
  for (const path of ["/finance", "/products", "/settings/history", "/insights"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { name: NO_ACCESS })).toHaveCount(0);
  }
});

test("vendeur : vend, lit le stock, ni l'argent ni les réglages", async ({ page, request }) => {
  const seller = await account(request, await roleId(request, "vendeur"));
  await login(page, seller);
  expect(await menu(page)).toEqual(["Accueil", "Vendre", "Stock", "Clients"]);
  await denied(page, "/finance", "/api/v1/analytics/money");
  await denied(page, "/settings", "/api/v1/companies/me");
  await denied(page, "/inventory/adjust", "/api/v1/inventory/movements");
  const headers = await tokenOf(request, seller);
  expect((await request.get("/api/v1/analytics/money", { headers })).status()).toBe(403);
});

test("comptable par défaut : l'historique des ventes, pas la caisse", async ({ page, request }) => {
  const accountant = await account(request, await roleId(request, "comptable"));
  await login(page, accountant);
  expect(await menu(page)).toEqual(["Accueil", "Vendre", "Stock", "Clients", "Argent"]);
  await expect(
    page
      .getByRole("navigation", { name: MAIN_MENU })
      .getByRole("link", { name: "Vendre", exact: true }),
  ).toHaveAttribute("href", "/sales");
  await denied(page, "/sales/new", "/api/v1/sales/customer-choices");
  await denied(page, "/settings/people", "/api/v1/users");
});

test("comptable restreint à « Encaisser une dette » : rien d'autre, menu et serveur", async ({
  page,
  request,
}) => {
  const client = await managerApi(request);
  const accountantRole = await roleId(request, "comptable");
  const accountant = await account(request, accountantRole);
  await login(page, accountant);
  const headers = await tokenOf(request, accountant);
  expect((await request.get("/api/v1/expenses", { headers })).status()).toBe(200);

  // Le gérant retire tout sauf un geste (les lignes verrouillées restent).
  await client.put(`/roles/${accountantRole}/abilities`, { abilities: ["base", "collect_debt"] });

  // Même jeton, requête suivante : le serveur refuse déjà.
  expect((await request.get("/api/v1/expenses", { headers })).status()).toBe(403);
  expect((await request.get("/api/v1/audit-logs", { headers })).status()).toBe(403);
  expect((await request.get("/api/v1/debts", { headers })).status()).toBe(200);

  // L'écran suit sans reconnexion : un refus relit l'identité.
  await page.goto("/finance/expenses");
  await expect(page.getByRole("heading", { name: NO_ACCESS })).toBeVisible();
  expect(await menu(page)).toEqual(["Accueil", "Argent"]);
  await expect(
    page
      .getByRole("navigation", { name: MAIN_MENU })
      .getByRole("link", { name: "Argent", exact: true }),
  ).toHaveAttribute("href", "/finance/debts");
  await denied(page, "/finance", "/api/v1/analytics/money");
  await denied(page, "/products", "/api/v1/inventory/stock");
  await denied(page, "/settings/history", "/api/v1/analytics/history");
  await denied(page, "/insights", "/api/v1/insights");
  await denied(page, "/sales", "/api/v1/sales");
  // Tuiles du tableau de bord : seulement ce qui s'ouvre.
  await page.goto("/dashboard");
  await expect(page.getByRole("link", { name: /Vendu aujourd.hui/ })).toHaveCount(0);
  await expect(page.getByRole("link", { name: /Dans la caisse/ })).toHaveCount(0);
});

test("rôle sur mesure : Accueil et Clients seulement", async ({ page, request }) => {
  const client = await managerApi(request);
  const custom = await client.post("/roles", {
    name: `Accueil ${Date.now()}`,
    permissions: ["dashboard:read", "notifications:read", "customers:read"],
  });
  const person = await account(request, custom.id);
  await login(page, person);
  expect(await menu(page)).toEqual(["Accueil", "Clients"]);
  await denied(page, "/sales", "/api/v1/sales");
  const headers = await tokenOf(request, person);
  expect((await request.get("/api/v1/sales", { headers })).status()).toBe(403);
  expect((await request.get("/api/v1/customers", { headers })).status()).toBe(200);
});
