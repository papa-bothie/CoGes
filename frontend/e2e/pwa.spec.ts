import { expect, test, type Page } from "@playwright/test";

import { E2E, loginThroughUi } from "./fixtures";

/**
 * Application installable (prompt 29, P2, ADR 0102), sur un build de production : le worker
 * s'enregistre, la page hors ligne s'affiche sans réseau, aucune réponse d'API ni page de la
 * boutique ne touche le Cache Storage, la déconnexion vide tout, et l'installation se propose
 * dans le menu.
 */
test.describe.configure({ timeout: 120_000, mode: "serial" });

async function login(page: Page) {
  await page.goto("/login");
  await loginThroughUi(page, E2E);
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
}

async function controlled(page: Page) {
  await page.waitForFunction(() => navigator.serviceWorker.ready.then(() => true));
  // Le premier chargement n'est pas encore contrôlé : on recharge une fois.
  if (!(await page.evaluate(() => Boolean(navigator.serviceWorker.controller)))) {
    await page.reload();
  }
  await expect
    .poll(() => page.evaluate(() => Boolean(navigator.serviceWorker.controller)))
    .toBe(true);
}

/** Toutes les adresses gardées dans le Cache Storage de cette origine. */
async function cachedUrls(page: Page): Promise<string[]> {
  return page.evaluate(async () => {
    const urls: string[] = [];
    for (const name of await caches.keys()) {
      const cache = await caches.open(name);
      for (const request of await cache.keys()) urls.push(new URL(request.url).pathname);
    }
    return urls;
  });
}

test("manifeste, worker et page hors ligne servis sans connexion", async ({ request }) => {
  const manifest = await request.get("/manifest.webmanifest");
  expect(manifest.ok()).toBeTruthy();
  expect((await manifest.json()).display).toBe("standalone");
  const worker = await request.get("/sw.js");
  expect(worker.headers()["cache-control"]).toContain("no-cache");
  expect(await worker.text()).toContain("pwa-e2e-1");
  expect((await request.get("/hors-ligne")).ok()).toBeTruthy();
});

test("une session complète ne laisse rien de la boutique dans le cache", async ({ page }) => {
  await login(page);
  await controlled(page);
  for (const path of ["/sales/new", "/products", "/customers", "/finance", "/dashboard"]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
  }
  const urls = await cachedUrls(page);
  expect(urls.length).toBeGreaterThan(0);
  const forbidden = urls.filter(
    (path) =>
      path.startsWith("/api/") ||
      !(
        path.startsWith("/_next/static/") ||
        path.startsWith("/icons/") ||
        path.startsWith("/brand/") ||
        path === "/hors-ligne" ||
        path === "/manifest.webmanifest"
      ),
  );
  expect(forbidden).toEqual([]);
});

test("sans réseau, la page hors ligne ; avec, la page demandée", async ({ page, context }) => {
  await login(page);
  await controlled(page);
  await context.setOffline(true);
  await page.goto("/customers").catch(() => undefined);
  await expect(page.getByRole("heading", { name: "Pas de connexion" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Réessayer" })).toBeVisible();
  await context.setOffline(false);
  await page.getByRole("link", { name: "Réessayer" }).click();
  await expect(page).toHaveURL(/\/customers$/);
  await expect(page.getByRole("heading", { name: "Pas de connexion" })).toHaveCount(0);
});

test("la déconnexion vide les caches de l'application", async ({ page }) => {
  await login(page);
  await controlled(page);
  await page.goto("/products");
  await page.waitForLoadState("networkidle");
  const before = await cachedUrls(page);
  expect(before.length).toBeGreaterThan(0);
  await page.getByRole("button", { name: "Réglages et compte" }).click();
  await page.getByRole("menuitem", { name: "Se déconnecter" }).click();
  await expect(page).toHaveURL(/\/login/);
  await page.waitForLoadState("networkidle");
  // Tout ce que la session avait gardé est parti ; la connexion ne remet que ses propres
  // fichiers statiques, jamais une donnée.
  const after = await cachedUrls(page);
  expect(before.filter((path) => !after.includes(path)).length).toBeGreaterThan(0);
  expect(after.filter((path) => !/^\/(_next\/static|brand|icons)\//.test(path))).toEqual([]);
});

test("l'installation se propose dans le menu, puis disparaît une fois installée", async ({
  page,
}) => {
  await login(page);
  // Chrome envoie `beforeinstallprompt` quand l'application est installable : on le simule.
  await page.evaluate(() => {
    const event = new Event("beforeinstallprompt", { cancelable: true }) as Event & {
      prompt: () => Promise<void>;
      userChoice: Promise<{ outcome: string }>;
    };
    event.prompt = async () => undefined;
    event.userChoice = Promise.resolve({ outcome: "accepted" });
    window.dispatchEvent(event);
  });
  await page.getByRole("button", { name: "Réglages et compte" }).click();
  await page.getByRole("menuitem", { name: "Installer l'application" }).click();
  await page.getByRole("button", { name: "Réglages et compte" }).click();
  await expect(page.getByRole("menuitem", { name: "Installer l'application" })).toHaveCount(0);
});
