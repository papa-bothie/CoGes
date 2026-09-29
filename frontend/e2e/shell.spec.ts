import { expect, test } from "@playwright/test";

import { createSalesperson, DEMO, loginThroughUi } from "./fixtures";

const CAPTURES = "../docs/design/captures/phase-11";

const NAVIGATION = [
  ["Tableau de bord", "/dashboard"],
  ["Ventes", "/sales"],
  ["Stock", "/inventory"],
  ["Produits", "/products"],
  ["Clients", "/customers"],
  ["Fournisseurs", "/suppliers"],
  ["Finance", "/finance"],
  ["Analytics", "/analytics"],
  ["CoGes Intelligence", "/insights"],
  ["Paramètres", "/settings"],
] as const;

test("connexion → coquille → navigation → rechargement → déconnexion", async ({ page }) => {
  // Sans session, une page protégée renvoie à la connexion en gardant la destination.
  await page.goto("/sales");
  await expect(page).toHaveURL(/\/login\?next=%2Fsales/);
  await page.screenshot({ path: `${CAPTURES}/login-clair.png` });

  await loginThroughUi(page, DEMO);
  await expect(page).toHaveURL(/\/sales$/);

  // En-tête : entreprise, utilisateur, rôle ; barre latérale sans sélecteur.
  const header = page.getByRole("banner");
  await expect(header.getByText("Gérant")).toBeVisible();
  const nav = page.getByRole("navigation", { name: "Navigation principale" });
  await expect(nav.getByRole("link")).toHaveText(NAVIGATION.map(([label]) => label));
  await expect(page.getByRole("combobox")).toHaveCount(0);
  await expect(page.getByText(/mode démonstration/i)).toHaveCount(0);

  for (const [label, href] of NAVIGATION) {
    await nav.getByRole("link", { name: label }).click();
    await expect(page).toHaveURL(new RegExp(`${href}$`));
    await expect(page.getByRole("heading", { level: 1, name: label })).toBeVisible();
    await expect(nav.getByRole("link", { name: label })).toHaveAttribute("aria-current", "page");
  }

  // Rechargement : le jeton en mémoire est perdu, le refresh silencieux le remplace.
  await nav.getByRole("link", { name: "Tableau de bord" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: "Tableau de bord" })).toBeVisible();
  await expect(header.getByText("Gérant")).toBeVisible();
  await page.screenshot({ path: `${CAPTURES}/coquille-clair.png` });

  // Thème sombre.
  await page.getByRole("button", { name: "Changer de thème" }).click();
  await page.getByRole("menuitemradio", { name: "Sombre" }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await expect(page.getByRole("menu")).toBeHidden();
  await page.screenshot({ path: `${CAPTURES}/coquille-sombre.png` });
  await page.getByRole("button", { name: "Changer de thème" }).click();
  await page.getByRole("menuitemradio", { name: "Clair" }).click();

  // La cloche mène aux notifications.
  await page.getByRole("link", { name: /^Notifications/ }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Notifications" })).toBeVisible();

  // Déconnexion : retour à la connexion, et l'application reste fermée.
  await page.getByRole("button", { name: "Se déconnecter" }).click();
  await expect(page).toHaveURL(/\/login\?reason=logout/);
  await expect(page.getByText("Vous êtes déconnecté.")).toBeVisible();
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login/);
});

test("identifiants faux : message générique de l'API", async ({ page }) => {
  await page.goto("/login");
  await loginThroughUi(page, { ...DEMO, password: "mauvais-mot-de-passe" });
  // `filter` : Next ajoute sa propre région `alert` (annonce des changements de route).
  await expect(page.getByRole("alert").filter({ hasText: /\S/ })).toHaveText(
    "Identifiants invalides.",
  );
  await expect(page).toHaveURL(/\/login/);
});

test("validation de surface avant tout appel", async ({ page }) => {
  await page.goto("/login");
  await loginThroughUi(page, { slug: "A B", email: "pas-un-email", password: "" });
  await expect(page.getByText("3 à 40 caractères")).toBeVisible();
  await expect(page.getByText("Adresse e-mail invalide.")).toBeVisible();
  await expect(page.getByText("Ce champ est obligatoire.")).toBeVisible();
});

test("session révoquée côté serveur : retour à la connexion", async ({ page, context }) => {
  await page.goto("/login");
  await loginThroughUi(page, DEMO);
  await expect(page).toHaveURL(/\/dashboard$/);
  // Le cookie de rafraîchissement disparaît (révocation, expiration…) : au rechargement,
  // le refresh échoue et la coquille renvoie à la connexion.
  await context.clearCookies({ name: "coges_refresh" });
  await page.reload();
  await expect(page).toHaveURL(/\/login\?reason=expired/);
  await expect(page.getByText("Votre session a expiré. Reconnectez-vous.")).toBeVisible();
});

test("vendeur : Paramètres masqué, rôle affiché", async ({ page, request }) => {
  const salesperson = await createSalesperson(request);
  await page.goto("/login");
  await loginThroughUi(page, salesperson);
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole("banner").getByText("Vendeur", { exact: true })).toBeVisible();
  const nav = page.getByRole("navigation", { name: "Navigation principale" });
  await expect(nav.getByRole("link", { name: "Ventes" })).toBeVisible();
  await expect(nav.getByRole("link", { name: "Paramètres" })).toHaveCount(0);
  await expect(nav.getByRole("link", { name: "Analytics" })).toHaveCount(0);
});
