import { expect, test } from "@playwright/test";

import { createSalesperson, DEMO, loginThroughUi } from "./fixtures";

const CAPTURES = "../docs/design/captures/phase-11";

/** Les cinq entrées de la maquette v2 (ADR 0070), puis Conseils. */
const NAVIGATION = [
  ["Accueil", "/dashboard"],
  // « Nouvelle vente » reprend le brouillon du jour s'il y en a un (ADR 0070).
  ["Vendre", "/sales/(new|[0-9a-f-]+/edit)"],
  ["Stock", "/products"],
  ["Clients", "/customers"],
  ["Argent", "/finance"],
] as const;

test("connexion → coquille → navigation → rechargement → déconnexion", async ({ page }) => {
  // Sans session, une page protégée renvoie à la connexion en gardant la destination.
  await page.goto("/sales");
  await expect(page).toHaveURL(/\/login\?next=%2Fsales/);
  await page.screenshot({ path: `${CAPTURES}/login-clair.png` });

  await loginThroughUi(page, DEMO);
  await expect(page).toHaveURL(/\/sales$/);

  // Barre du haut : logo et nom de la boutique, cinq entrées, Conseils, cloche, engrenage.
  const header = page.getByRole("banner");
  await expect(header.getByText("Alimentation Keur Fatou").first()).toBeVisible();
  const nav = page.getByRole("navigation", { name: "Menu principal" }).first();
  await expect(nav.getByRole("link")).toHaveText(NAVIGATION.map(([label]) => label));
  await expect(header.getByRole("link", { name: "Conseils" })).toBeVisible();
  // Aucun sélecteur d'entreprise dans la coquille (les écrans ont leurs propres filtres).
  await expect(header.getByRole("combobox")).toHaveCount(0);
  await expect(page.getByText(/mode démonstration/i)).toHaveCount(0);

  for (const [label, href] of NAVIGATION) {
    await nav.getByRole("link", { name: label }).click();
    await expect(page).toHaveURL(new RegExp(`${href}$`));
    await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
    await expect(nav.getByRole("link", { name: label })).toHaveAttribute("aria-current", "page");
  }

  // Rechargement : le jeton en mémoire est perdu, le refresh silencieux le remplace.
  await nav.getByRole("link", { name: "Accueil" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: /^Bonjour / })).toBeVisible();
  await page.screenshot({ path: `${CAPTURES}/coquille-clair.png` });

  // L'engrenage : la personne, son rôle, le mode sombre.
  await header.getByRole("button", { name: "Réglages et compte" }).click();
  await expect(page.getByRole("menu").getByText("Gérant")).toBeVisible();
  await page.getByRole("menuitem", { name: "Passer en mode sombre" }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await expect(page.getByRole("menu")).toBeHidden();
  await page.screenshot({ path: `${CAPTURES}/coquille-sombre.png` });
  await header.getByRole("button", { name: "Réglages et compte" }).click();
  await page.getByRole("menuitem", { name: "Passer en mode clair" }).click();

  // La cloche mène aux alertes.
  await header.getByRole("link", { name: /^Alertes/ }).click();
  await expect(page).toHaveURL(/\/notifications$/);

  // Déconnexion : retour à la connexion, et l'application reste fermée.
  await header.getByRole("button", { name: "Réglages et compte" }).click();
  await page.getByRole("menuitem", { name: "Se déconnecter" }).click();
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

test("vendeur : seulement Accueil, Vendre et Clients", async ({ page, request }) => {
  const salesperson = await createSalesperson(request);
  await page.goto("/login");
  await loginThroughUi(page, salesperson);
  await expect(page).toHaveURL(/\/dashboard$/);
  const nav = page.getByRole("navigation", { name: "Menu principal" }).first();
  await expect(nav.getByRole("link")).toHaveText(["Accueil", "Vendre", "Clients"]);
  await expect(page.getByRole("link", { name: "Conseils" })).toHaveCount(0);
  await page.getByRole("button", { name: "Réglages et compte" }).click();
  await expect(page.getByRole("menu").getByText("Vendeur", { exact: true })).toBeVisible();
  await expect(page.getByRole("menuitem", { name: "Réglages" })).toHaveCount(0);
});

test("redirection ouverte : next=/\\evil.example garde l'utilisateur sur le site", async ({
  page,
  baseURL,
}) => {
  const origin = new URL(baseURL ?? "http://localhost:3000").origin;
  // `%5C` : l'antislash tel qu'un lien piégé l'enverrait, décodé par `searchParams.get`.
  await page.goto("/login?next=/%5Cevil.example");
  await loginThroughUi(page, DEMO);
  await expect(page).toHaveURL(`${origin}/dashboard`);
  await expect(page.getByRole("heading", { level: 1, name: /^Bonjour / })).toBeVisible();
});
