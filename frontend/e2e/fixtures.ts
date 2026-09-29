import { expect, type APIRequestContext, type Page } from "@playwright/test";

export const DEMO = {
  slug: process.env.E2E_COMPANY_SLUG ?? "demo",
  email: process.env.E2E_EMAIL ?? "gerant@demo.example.com",
  password: process.env.E2E_PASSWORD ?? "demo-coges-2026",
};

export async function loginThroughUi(
  page: Page,
  credentials: { slug: string; email: string; password: string },
) {
  await page.getByLabel("Identifiant d'entreprise").fill(credentials.slug);
  await page.getByLabel("Adresse e-mail").fill(credentials.email);
  await page.getByLabel("Mot de passe").fill(credentials.password);
  await page.getByRole("button", { name: "Se connecter" }).click();
}

/** Jeton d'un gérant, obtenu par l'API **à travers la réécriture du front**. */
export async function managerToken(request: APIRequestContext): Promise<string> {
  const response = await request.post("/api/v1/auth/login", {
    data: { company_slug: DEMO.slug, email: DEMO.email, password: DEMO.password },
  });
  expect(response.ok()).toBeTruthy();
  return (await response.json()).access_token as string;
}

/** Crée un vendeur par les routes réelles et renvoie ses identifiants. */
export async function createSalesperson(request: APIRequestContext) {
  const token = await managerToken(request);
  const headers = { Authorization: `Bearer ${token}` };
  const roles = await (await request.get("/api/v1/roles?page_size=50", { headers })).json();
  const role = roles.items.find((item: { name: string }) => item.name === "vendeur");
  const email = `vendeur-e2e-${Date.now()}@${DEMO.slug}.example.com`;
  const password = "vendeur-e2e-2026";
  const created = await request.post("/api/v1/users", {
    headers,
    data: { email, full_name: "Vendeur E2E", password, role_ids: [role.id] },
  });
  expect(created.status()).toBe(201);
  return { slug: DEMO.slug, email, password };
}
