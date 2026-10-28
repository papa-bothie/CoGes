import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { E2E, loginThroughUi, managerApi, managerToken, type Credentials } from "./fixtures";

/**
 * Mots de passe (prompt 28, C2, ADR 0098) : « Afficher / Cacher » partout, et « Changer mon
 * mot de passe » depuis le menu du compte, pour le vendeur et le comptable aussi (ils n'ont
 * pas Réglages). Après le changement, l'ancien mot de passe ne marche plus, le nouveau oui.
 */
test.describe.configure({ timeout: 90_000, mode: "serial" });

/** Comptes créés ici : leur accès est coupé à la fin (plafond de l'offre, ADR 0091). */
const created: string[] = [];

test.afterAll(async ({ request }) => {
  const client = await managerApi(request);
  for (const id of created) await client.patch(`/users/${id}`, { is_active: false });
});

async function account(request: APIRequestContext, role: "vendeur" | "comptable") {
  const token = await managerToken(request, E2E);
  const headers = { Authorization: `Bearer ${token}` };
  const roles = await (await request.get("/api/v1/roles?page_size=50", { headers })).json();
  const roleId = roles.items.find((item: { name: string }) => item.name === role).id;
  const email = `${role}-mdp-${Date.now()}@${E2E.slug}.example.com`;
  const password = `${role}-ancien-2026`;
  const response = await request.post("/api/v1/users", {
    headers,
    data: { email, full_name: `Compte ${role}`, password, role_ids: [roleId] },
  });
  expect(response.status()).toBe(201);
  created.push((await response.json()).id as string);
  return { slug: E2E.slug, email, password } satisfies Credentials;
}

async function login(page: Page, credentials: Credentials) {
  await page.goto("/login");
  await loginThroughUi(page, credentials);
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
}

for (const role of ["vendeur", "comptable"] as const) {
  test(`${role} : change son mot de passe depuis le menu, puis se reconnecte avec le nouveau`, async ({
    page,
    request,
  }) => {
    const credentials = await account(request, role);
    const next = `${role}-nouveau-mot-2026`;
    await login(page, credentials);

    await page.getByRole("button", { name: "Réglages et compte" }).click();
    await page.getByRole("menuitem", { name: "Changer mon mot de passe" }).click();
    await expect(page.getByRole("heading", { name: "Changer mon mot de passe" })).toBeVisible();

    // La règle de longueur est là avant toute erreur.
    await expect(page.getByText("12 caractères au moins. Une phrase courte")).toBeVisible();
    const axe = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();
    expect(axe.violations).toEqual([]);

    await page.getByLabel("Mot de passe actuel", { exact: true }).fill(credentials.password);
    const fresh = page.getByLabel("Nouveau mot de passe", { exact: true });
    await fresh.fill(next);
    // Afficher, vérifier ce qu'on a tapé, puis le champ reste rempli.
    await page.getByRole("button", { name: "Afficher le mot de passe" }).nth(1).click();
    await expect(fresh).toHaveAttribute("type", "text");
    await expect(fresh).toHaveValue(next);

    // Concordance vérifiée avant l'envoi.
    const again = page.getByLabel("Retapez le nouveau mot de passe", { exact: true });
    await again.fill(`${next}-x`);
    await page.getByRole("button", { name: "Enregistrer le nouveau mot de passe" }).click();
    await expect(page.getByText("Les deux mots de passe ne sont pas identiques.")).toBeVisible();
    await expect(fresh).toHaveAttribute("type", "password");

    await again.fill(next);
    await page.getByRole("button", { name: "Enregistrer le nouveau mot de passe" }).click();
    await expect(page.getByRole("status")).toContainText("Mot de passe changé");

    // L'ancien ne marche plus, le nouveau oui.
    const old = await request.post("/api/v1/auth/login", {
      data: {
        company_slug: credentials.slug,
        email: credentials.email,
        password: credentials.password,
      },
    });
    expect(old.status()).toBe(401);
    await page.context().clearCookies();
    await login(page, { ...credentials, password: next });
  });
}

test("connexion : afficher puis cacher sans perdre ce qui est tapé", async ({ page }) => {
  await page.goto("/login");
  const field = page.getByLabel("Mot de passe", { exact: true });
  await field.fill("une phrase secrète");
  const show = page.getByRole("button", { name: "Afficher le mot de passe" });
  await expect(show).toHaveAttribute("aria-pressed", "false");
  const box = await show.boundingBox();
  expect(box?.height).toBeGreaterThanOrEqual(44);
  await show.click();
  await expect(field).toHaveAttribute("type", "text");
  await page.getByRole("button", { name: "Cacher le mot de passe" }).click();
  await expect(field).toHaveAttribute("type", "password");
  await expect(field).toHaveValue("une phrase secrète");
  expect(page.url()).not.toContain("secr");
});
