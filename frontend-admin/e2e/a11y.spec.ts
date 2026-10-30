import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { ADMIN, enterCode } from "./mfa";

/**
 * Accessibilité de chaque écran (prompt 27, D6) : axe AA sans violation en clair **et** en
 * sombre, et aucun défilement horizontal à 360 px. Depuis le prompt 31, le sombre vient du
 * choix mémorisé, pas du système : l'appareil est en sombre dans les deux cas.
 */

const SCREENS: { path: string; ready: (page: Page) => Promise<void> }[] = [
  {
    path: "/",
    ready: (page) => expect(page.getByRole("region", { name: "À traiter" })).toBeVisible(),
  },
  {
    path: "/companies",
    ready: (page) =>
      expect(page.getByRole("link", { name: "Parcours administration" }).first()).toBeVisible(),
  },
  { path: "/users", ready: (page) => expect(page.getByText(/\d+ comptes?/)).toBeVisible() },
  {
    path: "/team",
    ready: (page) =>
      expect(page.getByRole("heading", { name: "Ce que peut chaque profil" })).toBeVisible(),
  },
  { path: "/audit", ready: (page) => expect(page.getByText(/\d+ lignes?/)).toBeVisible() },
  {
    path: "/security",
    ready: (page) => expect(page.getByText(/Codes de secours encore utilisables/)).toBeVisible(),
  },
  {
    path: "/stats",
    ready: (page) => expect(page.getByText(/paiements? enregistrés?/)).toBeVisible(),
  },
  {
    path: "/system",
    ready: (page) => expect(page.getByRole("heading", { name: "Système" })).toBeVisible(),
  },
  {
    path: "/system/jobs",
    ready: (page) =>
      expect(page.getByRole("heading", { name: "Historique des tâches" })).toBeVisible(),
  },
];

async function signIn(page: Page): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("E-mail").fill(ADMIN.email);
  await page.getByLabel("Mot de passe", { exact: true }).fill(ADMIN.password);
  await page.getByRole("button", { name: "Se connecter" }).click();
  await enterCode(page);
  await expect(page.getByRole("heading", { name: "Tableau de bord" })).toBeVisible();
}

/**
 * Chaque `goto` recharge la page : le jeton d'accès, gardé en mémoire, est perdu et la session
 * se rouvre par un rafraîchissement, qui fait tourner le jeton de rafraîchissement. Un écran
 * peut être « prêt » avant la réponse ; repartir aussitôt l'interromprait (rotation faite côté
 * serveur, nouveau jeton jamais reçu). Le délai de grâce (ADR 0051) ne couvre qu'une seule
 * réponse perdue : deux de suite, et la session est révoquée pour réutilisation.
 */
async function openScreen(page: Page, screen: (typeof SCREENS)[number]): Promise<void> {
  const refreshed = page.waitForResponse(
    (response) => new URL(response.url()).pathname === "/api/v1/platform/auth/refresh",
  );
  await page.goto(screen.path);
  expect((await refreshed).status(), `${screen.path} : session rouverte`).toBe(200);
  await screen.ready(page);
}

async function axe(page: Page, where: string): Promise<void> {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  expect(results.violations, where).toEqual([]);
}

async function noHorizontalScroll(page: Page, where: string): Promise<void> {
  // Une fois la page posée (polices, données) : un débordement passager ne compte pas.
  await expect
    .poll(
      () =>
        page.evaluate(
          () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
        ),
      { message: where, timeout: 10_000 },
    )
    .toBeLessThanOrEqual(0);
}

for (const scheme of ["light", "dark"] as const) {
  test(`axe AA sur chaque écran, ${scheme === "light" ? "clair" : "sombre"}`, async ({ page }) => {
    test.setTimeout(180_000);
    await page.emulateMedia({ colorScheme: "dark" });
    await page.addInitScript((theme) => {
      window.localStorage.setItem("coges-admin:theme", theme);
    }, scheme);
    await page.goto("/login");
    await axe(page, `/login ${scheme}`);
    await page.goto("/invitation/lien-de-demonstration-sans-valeur-0000");
    await axe(page, `/invitation ${scheme}`);
    await signIn(page);
    for (const screen of SCREENS) {
      await openScreen(page, screen);
      await axe(page, `${screen.path} ${scheme}`);
    }
    // La fiche d'une entreprise et le tiroir du menu.
    await openScreen(page, SCREENS[1]!);
    await page.getByRole("link", { name: "Parcours administration" }).first().click();
    await expect(page.getByRole("region", { name: "Abonnement" })).toBeVisible();
    await axe(page, `fiche ${scheme}`);
  });
}

test("360 px : aucun défilement horizontal, menu en tiroir", async ({ page }) => {
  test.setTimeout(180_000);
  await page.setViewportSize({ width: 360, height: 760 });
  await page.goto("/login");
  await noHorizontalScroll(page, "/login");
  await signIn(page);
  for (const screen of SCREENS) {
    await openScreen(page, screen);
    await noHorizontalScroll(page, screen.path);
  }
  // Le repère « Administration » reste visible sur téléphone.
  await expect(page.getByText("Administration", { exact: true }).first()).toBeVisible();

  // Tiroir : ouvert par « Menu », Échap le ferme et rend le focus au bouton.
  const menu = page.getByRole("button", { name: "Menu" });
  await menu.click();
  const drawer = page.getByRole("dialog", { name: "Menu" });
  await expect(drawer.getByRole("link", { name: "Équipe" })).toBeVisible();
  await axe(page, "tiroir");
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
  await expect(menu).toBeFocused();
  // Une navigation depuis le tiroir le ferme, et la page courante est marquée.
  await menu.click();
  await drawer.getByRole("link", { name: "Utilisateurs" }).click();
  await expect(page.getByRole("heading", { name: "Utilisateurs" })).toBeVisible();
  await expect(drawer).toBeHidden();
  await menu.click();
  await expect(drawer.getByRole("link", { name: "Utilisateurs" })).toHaveAttribute(
    "aria-current",
    "page",
  );
});
