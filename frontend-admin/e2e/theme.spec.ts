import { expect, test, type Page } from "@playwright/test";

import { ADMIN, enterCode } from "./mfa";

/**
 * Thème de l'administration (prompt 31) : clair par défaut même sur un appareil en mode
 * sombre, bascule mémorisée dans le navigateur, posée avant l'affichage.
 */

test.use({ colorScheme: "dark" });

/** Thème du tout premier HTML rendu, avant toute hydratation (aucun éclair). */
async function themeAtFirstPaint(page: Page): Promise<string | null> {
  return page.evaluate(() => (window as unknown as { __firstTheme?: string }).__firstTheme ?? null);
}

test.beforeEach(async ({ page }) => {
  // Relève le thème au moment où <body> apparaît, avant React : c'est ce qui s'affiche.
  // Le script d'amorçage tourne avant que <html> existe : on observe le document.
  await page.addInitScript(() => {
    new MutationObserver((_, observer) => {
      if (document.body) {
        (window as unknown as { __firstTheme?: string }).__firstTheme =
          document.documentElement.dataset.theme;
        observer.disconnect();
      }
    }).observe(document, { childList: true, subtree: true });
  });
});

test("clair par défaut malgré un système sombre, bascule mémorisée, retour au clair", async ({
  page,
}) => {
  await page.goto("/login");
  const html = page.locator("html");
  await expect(html).toHaveAttribute("data-theme", "light");
  expect(await themeAtFirstPaint(page)).toBe("light");
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).colorScheme)).toBe(
    "light",
  );

  // Connexion, puis bascule depuis l'en-tête.
  await page.getByLabel("E-mail").fill(ADMIN.email);
  await page.getByLabel("Mot de passe", { exact: true }).fill(ADMIN.password);
  await page.getByRole("button", { name: "Se connecter" }).click();
  await enterCode(page);
  await expect(page.getByRole("heading", { name: "Tableau de bord" })).toBeVisible();
  await expect(html).toHaveAttribute("data-theme", "light");

  const toDark = page.getByRole("button", { name: "Passer en mode sombre" });
  await expect(toDark).toHaveAttribute("aria-pressed", "false");
  await toDark.click();
  await expect(html).toHaveAttribute("data-theme", "dark");
  const toLight = page.getByRole("button", { name: "Passer en mode clair" });
  await expect(toLight).toHaveAttribute("aria-pressed", "true");

  // Rechargement : le sombre est là dès le premier affichage.
  await page.reload();
  await expect(page.getByRole("heading", { name: "Tableau de bord" })).toBeVisible();
  await expect(html).toHaveAttribute("data-theme", "dark");
  expect(await themeAtFirstPaint(page)).toBe("dark");
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).colorScheme)).toBe(
    "dark",
  );

  // Second appui : retour au clair, mémorisé lui aussi.
  await page.getByRole("button", { name: "Passer en mode clair" }).click();
  await expect(html).toHaveAttribute("data-theme", "light");
  await page.reload();
  await expect(html).toHaveAttribute("data-theme", "light");
});

test("clavier seul : la bascule s'atteint et s'active, cible de 44 px", async ({ page }) => {
  await page.goto("/login");
  const toggle = page.getByRole("button", { name: "Passer en mode sombre" });
  const box = await toggle.boundingBox();
  expect(box?.width).toBeGreaterThanOrEqual(44);
  expect(box?.height).toBeGreaterThanOrEqual(44);
  for (let i = 0; i < 10 && !(await toggle.evaluate((el) => el === document.activeElement)); i++) {
    await page.keyboard.press("Tab");
  }
  await expect(toggle).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(page.getByRole("button", { name: "Passer en mode clair" })).toBeFocused();
});

test("l'invitation suit le même choix et l'onglet voisin suit la bascule", async ({ context }) => {
  const first = await context.newPage();
  await first.goto("/invitation/lien-de-demonstration-sans-valeur-0000");
  await expect(first.locator("html")).toHaveAttribute("data-theme", "light");
  const second = await context.newPage();
  await second.goto("/login");
  await second.getByRole("button", { name: "Passer en mode sombre" }).click();
  await expect(first.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(first.getByRole("button", { name: "Passer en mode clair" })).toBeVisible();
});

test("360 px : la bascule reste visible dans l'en-tête", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 760 });
  await page.goto("/login");
  await page.getByLabel("E-mail").fill(ADMIN.email);
  await page.getByLabel("Mot de passe", { exact: true }).fill(ADMIN.password);
  await page.getByRole("button", { name: "Se connecter" }).click();
  await enterCode(page);
  await expect(page.getByRole("heading", { name: "Tableau de bord" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Passer en mode sombre" })).toBeVisible();
});
