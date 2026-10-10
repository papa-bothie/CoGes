import { expect, test, type Locator, type Page } from "@playwright/test";

import { DEMO, emptyMyDrafts, loginThroughUi } from "./fixtures";

/**
 * Test du commerçant (critères de fin de la phase 15) : chaque parcours de caisse se mesure
 * en touches et en frappes clavier, et se chronomètre. On part de l'accueil, connecté ; une
 * touche est un clic, une frappe est une saisie au clavier. Catalogue de démonstration
 * (ADR 0060).
 */
test.describe.configure({ mode: "serial", timeout: 90_000 });

/** Compteur : chaque `tap` est une touche, chaque `type` une saisie au clavier. */
function counter(page: Page) {
  let taps = 0;
  let typed = 0;
  const started = Date.now();
  return {
    tap: async (target: Locator) => {
      taps += 1;
      await target.click();
    },
    type: async (target: Locator, text: string) => {
      typed += 1;
      await target.fill(text);
    },
    get typed() {
      return typed;
    },
    report: (name: string) => {
      const seconds = ((Date.now() - started) / 1000).toFixed(1);
      test.info().annotations.push({
        type: "commerçant",
        description: `${name} : ${taps} touches, ${typed} frappe${typed > 1 ? "s" : ""}, ${seconds} s`,
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
  // Un client qui a droit au crédit (le plus récent du seed peut avoir un plafond nul).
  const customer = page.getByRole("option", { name: /Dibiterie Chez Modou/ });
  await expect(customer).toBeVisible();
  await run.tap(customer);
  await expect(page.getByRole("button", { name: /Changer$/ })).toContainText(
    "Dibiterie Chez Modou",
  );
  await run.tap(page.getByRole("button", { name: "À crédit", exact: true }));
  await run.tap(page.getByRole("button", { name: "Enregistrer le crédit" }));
  await expect(page.getByRole("heading", { name: "Vente enregistrée" })).toBeVisible();
  await expect(page.getByText(/doit 750\sF$/)).toBeVisible();
  expect(run.report("vente à crédit")).toBeLessThanOrEqual(8);
});

test("créer un article : seuls le nom et les deux prix se tapent", async ({ page }) => {
  const name = `Savon de Marseille ${crypto.randomUUID().slice(0, 4)}`;
  const run = counter(page);
  await run.tap(page.getByRole("link", { name: "Stock", exact: true }).first());
  await run.tap(page.getByRole("link", { name: "Nouvel article" }));
  await run.type(page.getByLabel("Nom de l'article"), name);
  await run.type(page.getByLabel("Prix de vente (F)"), "500");
  await run.type(page.getByLabel("Prix d'achat (F)"), "350");
  // Le stock d'ouverture au compteur, sans clavier.
  for (let i = 0; i < 3; i += 1) {
    await run.tap(page.getByRole("button", { name: `Ajouter un ${name}` }).first());
  }
  await run.tap(page.getByRole("button", { name: "Enregistrer l'article" }));
  await expect(page.getByRole("heading", { name: `${name} est ajouté` })).toBeVisible();
  await expect(page.getByText(/3 pièces en stock · vendu 500\sF/)).toBeVisible();
  expect(run.typed).toBe(3);
  expect(run.report("créer un article")).toBeLessThanOrEqual(6);
});

test("corriger le stock, 2 sacs abîmés : 5 touches au plus, aucune frappe", async ({ page }) => {
  const name = "Riz brisé parfumé, sac 25 kg";
  const run = counter(page);
  await run.tap(page.getByRole("link", { name: "Stock", exact: true }).first());
  await run.tap(page.getByRole("link", { name: "Corriger le stock" }));
  await run.tap(page.getByRole("radio", { name: new RegExp(`^${name}`) }));
  await expect(page.getByLabel(`Quantité : ${name}`)).toHaveValue("1");
  // « Moins » et « Abîmé ou cassé » sont déjà choisis : 1 devient 2 au compteur.
  await run.tap(page.getByRole("button", { name: `Ajouter un ${name}` }));
  await expect(page.getByRole("radio", { name: "Abîmé ou cassé" })).toHaveAttribute(
    "aria-checked",
    "true",
  );
  await run.tap(page.getByRole("button", { name: "Valider la correction" }));
  await expect(
    page.getByText(new RegExp(`^${name} : .* maintenant \\(abîmé ou cassé\\)\\.$`)),
  ).toBeVisible();
  expect(run.typed).toBe(0);
  expect(run.report("corriger le stock")).toBeLessThanOrEqual(5);
});
