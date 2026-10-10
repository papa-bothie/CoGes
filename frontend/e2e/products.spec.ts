import { expect, test, type Page } from "@playwright/test";

import { E2E, loginThroughUi } from "./fixtures";

const CAPTURES = "../docs/design/captures/phase-12";
const shot = (page: Page, name: string) =>
  page.screenshot({ path: `${CAPTURES}/${name}.png`, fullPage: true, animations: "disabled" });

test.describe.configure({ timeout: 90_000 });

async function login(page: Page) {
  await page.goto("/login");
  await loginThroughUi(page, E2E);
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
}

test("rayons, création d'un article, changement de prix, correction du stock", async ({ page }) => {
  const marker = crypto.randomUUID().slice(0, 6);
  const draft = `Rayon ${marker}`;
  const shelf = `Rangée ${marker}`;
  const name = `Savon ${marker}`;
  await login(page);

  // Rayons (maquette 12) : ajouter avec une couleur, renommer sur place ; un rayon vide
  // se supprime, un rayon qui porte un article ne se supprime pas.
  await page.goto("/products/categories");
  const shelves = page.getByRole("list", { name: "Rayons" });
  await page.getByLabel("Nouveau rayon").fill(draft);
  await page.getByRole("radio", { name: "Vert", exact: true }).click();
  await page.getByRole("button", { name: "Ajouter", exact: true }).click();
  const row = shelves.getByRole("listitem").filter({ hasText: draft });
  await expect(row).toContainText("Aucun article");
  await expect(page.getByRole("button", { name: `Supprimer ${draft}` })).toBeEnabled();
  await page.getByRole("button", { name: `Renommer ${draft}` }).click();
  await page.getByLabel(`Nouveau nom de ${draft}`).fill(shelf);
  await page.getByRole("button", { name: "Enregistrer", exact: true }).click();
  await expect(shelves.getByRole("listitem").filter({ hasText: shelf })).toBeVisible();
  await shot(page, "categories");

  // Création d'un article dans ce rayon, avec son stock, puis l'écran de succès.
  await page.goto("/products/new");
  await page.getByLabel("Nom de l'article").fill(name);
  await page.getByLabel("Prix de vente (F)").fill("750");
  await page.getByLabel("Prix d'achat (F)").fill("500");
  await expect(page.getByText(/Vous gagnez 250\sF sur chaque pièce/)).toBeVisible();
  await page.getByRole("button", { name: shelf, exact: true }).click();
  await page.getByLabel("Quantité en stock").fill("12");
  await page.getByLabel("Seuil d’alerte").fill("5");
  await shot(page, "produit-formulaire");
  await page.getByRole("button", { name: "Enregistrer l'article" }).click();
  await expect(page.getByRole("heading", { name: `${name} est ajouté` })).toBeVisible();
  await expect(page.getByText(/12 pièces en stock · vendu 750\sF/)).toBeVisible();

  await page.goto("/products/categories");
  await expect(shelves.getByRole("listitem").filter({ hasText: shelf })).toContainText("1 article");
  await expect(page.getByRole("button", { name: `Supprimer ${shelf}` })).toBeDisabled();

  // Écran Stock (maquette 07) : recherche, quantité, puis la fiche.
  await page.goto("/products");
  await page.getByRole("searchbox", { name: "Chercher un article" }).fill(name);
  await expect(page).toHaveURL(/search=/);
  const line = page.getByRole("link").filter({ hasText: name });
  await expect(line).toContainText("12 pièces");
  await line.click();
  await expect(page).toHaveURL(/\/products\/[0-9a-f-]+$/);
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
  await expect(page.getByText(`${shelf} · vendu par pièce`)).toBeVisible();

  // Changer les prix sur place.
  await page.getByRole("button", { name: "Changer les prix" }).click();
  await page.getByLabel("Prix de vente (F)").fill("800");
  await page.getByRole("button", { name: "Enregistrer", exact: true }).click();
  await expect(page.getByText("Prix enregistrés.")).toBeVisible();
  await expect(page.getByText(/^800\sF$/).first()).toBeVisible();
  await expect(page.getByText(/^12 pièces$/)).toBeVisible();

  // Correction depuis la fiche : l'article est déjà choisi, la raison en tuile.
  await page.getByRole("link", { name: "Corriger le stock" }).click();
  await expect(page).toHaveURL(/\/inventory\/adjust\?product=/);
  await expect(page.getByRole("radio", { name: new RegExp(name) })).toHaveAttribute(
    "aria-checked",
    "true",
  );
  await page.getByRole("radio", { name: "Plus", exact: true }).click();
  await page.getByLabel(`Quantité : ${name}`).fill("2");
  await expect(page.getByRole("status").filter({ hasText: "Après" })).toContainText(
    "Après : 14 pièces",
  );
  await page.getByRole("radio", { name: "Retrouvé" }).click();
  await page.getByRole("button", { name: "Valider la correction" }).click();
  await expect(page.getByText(`${name} : 14 pièces maintenant (retrouvé).`)).toBeVisible();
  await page.goBack();
  await expect(page.getByText(/^14 pièces$/)).toBeVisible();
  await shot(page, "fiche-produit");
});

test("créer un article en moins de 8 touches", async ({ page }) => {
  const name = `Riz ${crypto.randomUUID().slice(0, 6)}`;
  await login(page);
  await page.goto("/products/new");
  await expect(page.getByRole("heading", { level: 1, name: "Nouvel article" })).toBeVisible();

  // Chaque saisie ou toucher compte pour un.
  let touches = 0;
  const touch = async (action: Promise<void>) => {
    touches += 1;
    await action;
  };
  await touch(page.getByLabel("Nom de l'article").fill(name));
  await touch(page.getByLabel("Prix de vente (F)").fill("15500"));
  await touch(page.getByLabel("Prix d'achat (F)").fill("14000"));
  await touch(page.getByRole("button", { name: "Sac", exact: true }).click());
  await touch(page.getByLabel("Quantité en stock").fill("10"));
  await touch(page.getByRole("button", { name: "Enregistrer l'article" }).click());
  expect(touches).toBeLessThan(8);
  await expect(page.getByRole("heading", { name: `${name} est ajouté` })).toBeVisible();

  // Référence et code-barres générés par le serveur (ADR 0066).
  await page.goto("/products");
  await page.getByRole("searchbox", { name: "Chercher un article" }).fill(name);
  await expect(page).toHaveURL(/search=/);
  await page.getByRole("link").filter({ hasText: name }).click();
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
  await expect(page.getByText(/^10 sacs$/)).toBeVisible();
  await page.getByRole("button", { name: /Plus d.infos/ }).click();
  await expect(page.getByText(/^ART-\d{4,}$/)).toBeVisible();
  await expect(page.getByText(/^2\d{12}$/).first()).toBeVisible();
});
