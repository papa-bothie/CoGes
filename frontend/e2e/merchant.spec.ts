import { expect, test, type Locator, type Page } from "@playwright/test";

import { DEMO, emptyMyDrafts, loginThroughUi } from "./fixtures";

/**
 * Test du commerçant (critères de fin de la phase 15) : chaque parcours de caisse se mesure
 * en touches et en frappes clavier, et se chronomètre. On part de l'accueil, connecté ; une
 * touche est un clic, une frappe est une saisie au clavier. Catalogue de démonstration
 * (ADR 0060).
 */
test.describe.configure({ mode: "serial", timeout: 90_000 });

/** Compteur : chaque `tap` est une touche ; aucune saisie clavier n'est faite ici. */
function counter(page: Page) {
  let taps = 0;
  const started = Date.now();
  return {
    tap: async (target: Locator) => {
      taps += 1;
      await target.click();
    },
    report: (name: string) => {
      const seconds = ((Date.now() - started) / 1000).toFixed(1);
      test.info().annotations.push({
        type: "commerçant",
        description: `${name} : ${taps} touches, 0 frappe, ${seconds} s`,
      });
      return taps;
    },
    page,
  };
}

test.beforeEach(async ({ page, request }) => {
  await emptyMyDrafts(request, DEMO);
  await page.goto("/login");
  await loginThroughUi(page, DEMO);
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
  await expect(page.getByRole("link", { name: "Nouvelle vente" }).first()).toBeVisible();
});

async function addTile(page: Page, tap: (target: Locator) => Promise<void>, name: string) {
  const tile = page.getByRole("button", { name: `Ajouter ${name}`, exact: true });
  await expect(tile).toBeEnabled();
  await tap(tile);
  await expect(page.getByRole("textbox", { name: `Quantité de ${name}` })).toBeVisible();
  await page.waitForLoadState("networkidle");
}

test("vente comptant de 3 articles avec rendu de monnaie : 7 touches au plus", async ({ page }) => {
  const run = counter(page);
  await run.tap(page.getByRole("link", { name: "Nouvelle vente" }).first());
  await expect(page.getByRole("heading", { name: "Nouvelle vente" })).toBeVisible();
  for (const name of [
    "Sucre en poudre",
    "Huile végétale au détail",
    "Huile d'arachide, bidon 5 L",
  ]) {
    await addTile(page, run.tap, name);
  }
  // 750 + 1 300 + 7 500 = 9 550 F ; le client donne un billet de 10 000.
  await expect(page.getByRole("button", { name: /^Encaisser 9\s550\sF$/ })).toBeEnabled();
  await run.tap(page.getByRole("button", { name: /^10\s000$/ }));
  await expect(page.getByText(/450\sF/).first()).toBeVisible();
  await run.tap(page.getByRole("button", { name: /^Encaisser/ }));
  await expect(page.getByRole("heading", { name: "Vente enregistrée" })).toBeVisible();
  expect(run.report("vente comptant")).toBeLessThanOrEqual(7);
});

test("vente à crédit à un client existant : 8 touches au plus", async ({ page }) => {
  const run = counter(page);
  await run.tap(page.getByRole("link", { name: "Nouvelle vente" }).first());
  await addTile(page, run.tap, "Sucre en poudre");
  await run.tap(page.getByRole("button", { name: /Changer$/ }));
  // Le premier client après « Client de passage » : les plus récents viennent en tête.
  const customer = page.getByRole("option").nth(1);
  await expect(customer).toBeVisible();
  await run.tap(customer);
  await expect(page.getByRole("button", { name: /Changer$/ })).not.toContainText(
    "Client de passage",
  );
  await run.tap(page.getByRole("button", { name: "À crédit", exact: true }));
  await run.tap(page.getByRole("button", { name: "Enregistrer le crédit" }));
  await expect(page.getByRole("heading", { name: "Vente enregistrée" })).toBeVisible();
  await expect(page.getByText(/doit 750\sF$/)).toBeVisible();
  expect(run.report("vente à crédit")).toBeLessThanOrEqual(8);
});
