// Parcours navigateur de l'installation sur site (ADR 0124), lancé par le workflow
// « Sur site » et par deploy/onprem-ci/verifier.sh :
//
//   node deploy/onprem-ci/parcours.mjs
//
// Sous Chromium, sur http://localhost : le gérant se connecte, recharge la page et reste
// connecté (le cookie Secure du rafraîchissement est donc accepté sur http://localhost),
// le service worker s'enregistre, un article est créé puis vendu. Aucune requête du
// navigateur ne doit viser autre chose que cette origine.
//
// Playwright n'est pas une dépendance de ce dossier : on réutilise celui de `frontend/`,
// déjà installé (pnpm install), sans rien y modifier.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const { chromium, expect } = createRequire(path.join(root, "frontend", "package.json"))(
  "@playwright/test",
);

const BASE = (process.env.ONPREM_URL ?? "http://localhost").replace(/\/+$/, "");
const SLUG = process.env.ONPREM_SLUG ?? "boutique-test";
const EMAIL = process.env.ONPREM_EMAIL ?? "gerant@boutique.example";
const PASSWORD = process.env.ONPREM_PASSWORD;
assert(PASSWORD, "ONPREM_PASSWORD manque (mot de passe du gérant créé par create-company)");

const ARTICLE = `Savon sur site ${Date.now().toString(36)}`;
const TIMEOUT = 30_000;
expect.configure?.({ timeout: TIMEOUT });

function step(text) {
  console.log(`• ${text}`);
}

const browser = await chromium.launch();
const context = await browser.newContext({ locale: "fr-FR" });
context.setDefaultTimeout(TIMEOUT);
const page = await context.newPage();

// Tout ce que le navigateur demande, service worker compris.
const outside = new Set();
context.on("request", (request) => {
  const url = request.url();
  if (/^(data|blob|about|chrome-extension):/.test(url)) return;
  if (new URL(url).origin !== BASE) outside.add(url);
});

try {
  step(`connexion sur ${BASE}/login`);
  await page.goto(`${BASE}/login`);
  await expect(page.locator("form input:focus")).toHaveCount(1, { timeout: TIMEOUT });
  await page.getByLabel("Code de la boutique").fill(SLUG);
  await page.getByLabel("Votre e-mail ou téléphone").fill(EMAIL);
  await page.getByLabel("Mot de passe", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Entrer" }).click();

  // Première connexion : les textes légaux (ADR 0117). Aux suivantes, l'accueil directement.
  const legal = page.getByRole("heading", { name: "Avant de continuer" });
  const home = page.getByRole("heading", { level: 1, name: /^Bonjour / });
  await legal.or(home).first().waitFor({ timeout: TIMEOUT });
  if (await legal.isVisible()) {
    step("textes légaux acceptés");
    await page.getByRole("checkbox", { name: /J'ai lu et j'accepte/ }).check();
    await page.getByRole("button", { name: "Accepter et continuer" }).click();
  }
  await expect(home).toBeVisible({ timeout: TIMEOUT });

  step("cookie de rafraîchissement Secure accepté sur http://localhost");
  const cookies = await context.cookies(`${BASE}/api/v1/auth/refresh`);
  const refresh = cookies.find((cookie) => cookie.name === "coges_refresh");
  assert(refresh, "le cookie coges_refresh n'a pas été gardé par le navigateur");
  assert.equal(refresh.secure, true, "le cookie coges_refresh devrait être Secure");
  assert.equal(refresh.httpOnly, true);

  step("rechargement : toujours connecté");
  await page.reload();
  await expect(home).toBeVisible({ timeout: TIMEOUT });
  await expect(page).toHaveURL(/\/dashboard$/);

  step("service worker enregistré");
  const worker = await page.evaluate(
    () =>
      Promise.race([
        navigator.serviceWorker.ready.then((registration) => registration.active?.scriptURL),
        new Promise((resolve) => setTimeout(() => resolve(null), 20_000)),
      ]),
  );
  assert.equal(worker, `${BASE}/sw.js`, "le service worker ne s'est pas enregistré");

  step(`article créé : ${ARTICLE}`);
  await page.getByRole("link", { name: "Stock", exact: true }).first().click();
  await page.getByRole("link", { name: "Nouvel article" }).click();
  await page.getByLabel("Nom de l'article").fill(ARTICLE);
  await page.getByLabel("Prix de vente (F)").fill("500");
  await page.getByLabel("Prix d'achat (F)").fill("350");
  for (let i = 0; i < 3; i += 1) {
    await page.getByRole("button", { name: `Ajouter un ${ARTICLE}` }).first().click();
  }
  await page.getByRole("button", { name: "Enregistrer l'article" }).click();
  await expect(page.getByRole("heading", { name: `${ARTICLE} est ajouté` })).toBeVisible({
    timeout: TIMEOUT,
  });

  step("vente comptant d'un article");
  await page.goto(`${BASE}/dashboard`);
  await page.getByRole("link", { name: "Nouvelle vente" }).first().click();
  await expect(page.getByRole("heading", { name: "Nouvelle vente" })).toBeVisible({
    timeout: TIMEOUT,
  });
  const tile = page.getByRole("button", { name: `Ajouter ${ARTICLE}`, exact: true });
  await expect(tile).toBeEnabled({ timeout: TIMEOUT });
  await tile.click();
  await expect(page.getByRole("textbox", { name: `Quantité de ${ARTICLE}` })).toBeVisible({
    timeout: TIMEOUT,
  });
  const pay = page.getByRole("button", { name: /^Encaisser 500\sF$/ });
  await expect(pay).toBeEnabled({ timeout: TIMEOUT });
  await pay.click();
  await expect(page.getByRole("heading", { name: "Vente enregistrée" })).toBeVisible({
    timeout: TIMEOUT,
  });

  step("aucune requête hors de l'origine");
  assert.deepEqual([...outside], [], "le navigateur a demandé autre chose que http://localhost");
  console.log("OK — parcours sur site réussi.");
} catch (error) {
  await page.screenshot({ path: process.env.ONPREM_SCREENSHOT ?? "onprem-echec.png" }).catch(() => {});
  console.error(`ÉCHEC sur ${page.url()}`);
  throw error;
} finally {
  await browser.close();
}
