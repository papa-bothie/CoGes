import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

/**
 * Statistiques (ADR 0093). Le revenu ne bouge qu'avec un paiement enregistré : on en
 * déclare un par l'API sur l'entreprise `support-e2e` (créée par `e2e.sh reset`), puis
 * l'écran le compte après « Actualiser ».
 */
const ADMIN = { email: "admin@e2e.example.com", password: "admin-coges-e2e-2026" };
const API = "http://localhost:8100/api/v1";

async function axe(page: Page): Promise<void> {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  expect(results.violations).toEqual([]);
}

async function platformHeaders(request: APIRequestContext): Promise<Record<string, string>> {
  const login = await request.post(`${API}/platform/auth/login`, { data: ADMIN });
  expect(login.ok()).toBeTruthy();
  return { Authorization: `Bearer ${(await login.json()).access_token}` };
}

async function paymentCount(request: APIRequestContext, headers: Record<string, string>) {
  const response = await request.get(`${API}/platform/stats/revenue`, { headers });
  expect(response.ok()).toBeTruthy();
  return (await response.json()).payment_count as number;
}

function countText(count: number): RegExp {
  return new RegExp(`^${count} paiements? enregistrés? du `);
}

test("statistiques : compteurs datés, revenu déclaré, nouvelles entreprises", async ({
  page,
  request,
}) => {
  const headers = await platformHeaders(request);
  const before = await paymentCount(request, headers);

  await page.goto("/login");
  await page.getByLabel("E-mail").fill(ADMIN.email);
  await page.getByLabel("Mot de passe", { exact: true }).fill(ADMIN.password);
  await page.getByRole("button", { name: "Se connecter" }).click();
  await expect(page.getByRole("heading", { name: "Tableau de bord" })).toBeVisible();
  await page.goto("/companies");
  await page.getByRole("link", { name: "Statistiques" }).click();
  await expect(page.getByRole("heading", { name: "Statistiques" })).toBeVisible();
  await expect(page.getByText(/^Comptés le \d\d\/\d\d\/\d{4} à \d\d:\d\d/)).toBeVisible();
  await expect(page.getByRole("row", { name: /Premium/ })).toBeVisible();
  await expect(
    page.getByText(/Basé sur les paiements enregistrés, pas sur les offres en cours/),
  ).toBeVisible();
  await expect(page.getByText(countText(before))).toBeVisible();
  await axe(page);

  // Un paiement déclaré (ADR 0091) : le revenu du mois le compte, une fois.
  const companies = await request.get(`${API}/platform/companies`, {
    headers,
    params: { search: "support-e2e" },
  });
  const [shop] = (await companies.json()).items as [{ id: string }];
  const paid = await request.post(`${API}/platform/companies/${shop.id}/payments`, {
    headers: { ...headers, "Idempotency-Key": crypto.randomUUID() },
    data: { amount_fcfa: "4900", paid_at: new Date().toISOString(), method: "cash" },
  });
  expect(paid.status()).toBe(201);
  await page.getByRole("button", { name: "Actualiser" }).click();
  await expect(page.getByText(countText(before + 1))).toBeVisible();

  // Une période personnalisée impossible : le message du serveur, pas un chiffre.
  await page.getByText("Personnalisée", { exact: true }).click();
  await page.getByLabel("Du").fill("2025-01-01");
  await page.getByLabel("Au").fill("2026-06-30");
  await page.getByRole("button", { name: "Afficher" }).click();
  const revenue = page.getByRole("region", { name: "Revenu" });
  await expect(revenue.getByRole("alert")).toHaveText("La période ne peut pas dépasser 366 jours.");

  // Nouvelles entreprises, par semaine, avec les chiffres exacts.
  await page.getByText("Par semaine", { exact: true }).click();
  await page.getByText("Voir les chiffres").click();
  await expect(page.getByRole("row", { name: /^Semaine du/ })).toHaveCount(52);
  await axe(page);
});
