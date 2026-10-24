import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

/** Créés par `deploy/scripts/e2e.sh reset` (ADR 0089), sans valeur hors de coges_e2e. */
const ADMIN = { email: "admin@e2e.example.com", password: "admin-coges-e2e-2026" };
const SHOP = {
  slug: "admin-e2e",
  email: "gerant@admin-e2e.example.com",
  password: "demo-coges-2026",
};
const API = "http://localhost:8100/api/v1";

async function signIn(page: Page): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("E-mail").fill(ADMIN.email);
  await page.getByLabel("Mot de passe").fill(ADMIN.password);
  await page.getByRole("button", { name: "Se connecter" }).click();
  await expect(page.getByRole("heading", { name: "Tableau de bord" })).toBeVisible();
  await page.goto("/companies");
}

async function axe(page: Page): Promise<void> {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  expect(results.violations).toEqual([]);
}

test("connexion : un mauvais mot de passe est refusé sans dire pourquoi", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "Administration" })).toBeVisible();
  await axe(page);
  await page.getByLabel("E-mail").fill(ADMIN.email);
  await page.getByLabel("Mot de passe").fill("pas-le-bon-mot-de-passe");
  await page.getByRole("button", { name: "Se connecter" }).click();
  // Le formulaire seul : Next annonce aussi les changements de route dans un `alert`.
  await expect(page.locator("form").getByRole("alert")).toHaveText(
    "E-mail ou mot de passe incorrect.",
  );
});

test("sans session, toute page renvoie à la connexion", async ({ page }) => {
  await page.goto("/companies");
  await expect(page).toHaveURL(/\/login$/);
});

test("liste et détail : métadonnées seulement", async ({ page }) => {
  await signIn(page);
  await axe(page);
  await page.getByLabel("Nom ou code").fill("admin-e2e");
  await page.getByRole("button", { name: "Chercher" }).click();
  const row = page.getByRole("row", { name: /Parcours administration/ });
  // Toute entreprise naît en essai (ADR 0091).
  await expect(row).toContainText("Essai");
  await row.getByRole("link", { name: "Parcours administration" }).click();

  await expect(page.getByRole("heading", { name: "Parcours administration" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "Gérant suspendu" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "Gérant", exact: true })).toBeVisible();
  // Aucun montant de l'entreprise, aucune vente : les seuls « FCFA » de la page sont ceux
  // de son abonnement à CoGes (ADR 0091).
  const subscription = page.getByRole("region", { name: "Abonnement" });
  await expect(subscription).toBeVisible();
  const everywhere = await page.getByText(/FCFA/).count();
  expect(everywhere).toBe(await subscription.getByText(/FCFA/).count());
  await expect(page.getByRole("region", { name: "Comptes" }).getByText(/FCFA/)).toHaveCount(0);
  await axe(page);
});

test("suspendre demande confirmation, coupe la connexion commerçante, puis réactiver la rend", async ({
  page,
  request,
}) => {
  await signIn(page);
  await page.getByLabel("Nom ou code").fill("admin-e2e");
  await page.getByRole("button", { name: "Chercher" }).click();
  await page.getByRole("link", { name: "Parcours administration" }).click();

  await page.getByRole("button", { name: "Suspendre l'entreprise" }).click();
  const dialog = page.getByRole("dialog", { name: "Suspendre Parcours administration ?" });
  await expect(dialog).toBeVisible();
  // Action destructrice : « Annuler » a le focus.
  await expect(dialog.getByRole("button", { name: "Annuler" })).toBeFocused();
  await axe(page);
  // Annuler : rien ne change.
  await dialog.getByRole("button", { name: "Annuler" }).click();
  await expect(page.getByText("Essai", { exact: true }).first()).toBeVisible();

  await page.getByRole("button", { name: "Suspendre l'entreprise" }).click();
  await dialog.getByLabel("Raison").fill("Parcours e2e : suspension");
  await dialog.getByRole("button", { name: "Suspendre Parcours administration" }).click();
  await expect(page.getByRole("status").filter({ hasText: "suspendue" })).toContainText(
    "Parcours administration est suspendue.",
  );
  await expect(page.getByRole("link", { name: "Voir dans le journal" })).toBeVisible();
  await expect(page.getByText("Suspendue", { exact: true })).toBeVisible();

  const refused = await request.post(`${API}/auth/login`, {
    data: { company_slug: SHOP.slug, email: SHOP.email, password: SHOP.password },
  });
  expect(refused.status()).toBe(403);
  expect((await refused.json()).error.code).toBe("company_suspended");

  // Réactiver : confirmation légère, sans raison (D5).
  await page.getByRole("button", { name: "Réactiver l'entreprise" }).click();
  const reactivate = page.getByRole("dialog", { name: "Réactiver Parcours administration ?" });
  await reactivate.getByRole("button", { name: "Réactiver Parcours administration" }).click();
  await expect(page.getByRole("status").filter({ hasText: "réactivée" })).toContainText(
    "Parcours administration est réactivée.",
  );

  const allowed = await request.post(`${API}/auth/login`, {
    data: { company_slug: SHOP.slug, email: SHOP.email, password: SHOP.password },
  });
  expect(allowed.status()).toBe(200);
});
