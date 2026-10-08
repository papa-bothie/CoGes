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

test("catégories, création d'un article, changement de prix, correction du stock", async ({
  page,
}) => {
  const marker = crypto.randomUUID().slice(0, 6);
  const parent = `Rayon ${marker}`;
  const child = `Sous-rayon ${marker}`;
  const name = `Savon ${marker}`;
  await login(page);

  // Catégories : un parent, un enfant ; supprimer le parent est refusé par le serveur.
  await page.goto("/products/categories");
  await page.getByRole("button", { name: "Nouvelle catégorie" }).click();
  await page.getByRole("dialog").getByLabel("Nom", { exact: true }).fill(parent);
  await page.getByRole("dialog").getByRole("button", { name: "Enregistrer" }).click();
  await expect(page.getByRole("treeitem", { name: new RegExp(parent) })).toBeVisible();
  await page.getByRole("button", { name: `Ajouter une sous-catégorie à ${parent}` }).click();
  await page.getByRole("dialog").getByLabel("Nom", { exact: true }).fill(child);
  await page.getByRole("dialog").getByRole("button", { name: "Enregistrer" }).click();
  await expect(page.getByRole("treeitem", { name: new RegExp(child) })).toHaveAttribute(
    "aria-level",
    "2",
  );
  await page.getByRole("button", { name: `Supprimer ${parent}` }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Supprimer" }).click();
  await expect(page.getByRole("dialog").getByRole("alert")).toBeVisible();
  await page.getByRole("dialog").getByRole("button", { name: "Fermer", exact: true }).click();
  await shot(page, "categories");

  // Création d'un article dans la sous-catégorie, avec son stock (lot 1 : formulaire court).
  await page.goto("/products/new");
  await page.getByLabel("Nom de l'article").fill(name);
  await page.getByLabel("Prix de vente (F)").fill("750");
  await page.getByLabel("Prix d'achat (F)").fill("500");
  await expect(page.getByText(/Vous gagnez 250\sF sur chaque pièce/)).toBeVisible();
  await page.getByRole("button", { name: child, exact: true }).click();
  const [stockField, warnField] = await page.getByLabel(`Quantité : ${name}`).all();
  await stockField!.fill("12");
  await warnField!.fill("5");
  await shot(page, "produit-formulaire");
  await page.getByRole("button", { name: "Enregistrer l'article" }).click();

  await expect(page).toHaveURL(/\/products\/[0-9a-f-]+$/);
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
  await expect(page.getByText(`${parent} › ${child}`)).toBeVisible();

  // Changement de prix : la frise garde l'ancien et marque le nouveau « Actuel ».
  await page.getByRole("button", { name: "Changer le prix" }).click();
  await page.getByLabel("Nouveau prix de vente").fill("800");
  await page.getByRole("dialog").getByRole("button", { name: "Enregistrer" }).click();
  await expect(page.getByText("Prix mis à jour.")).toBeVisible();
  const history = page.getByRole("list").filter({ hasText: "Actuel" });
  await expect(history.getByRole("listitem")).toHaveCount(2);

  await expect(page.getByText(/^12 pièces$/)).toBeVisible();

  // Correction depuis la fiche : l'article est déjà choisi, la raison en tuile.
  await page.getByRole("button", { name: "Corriger le stock" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText(name)).toBeVisible();
  await dialog.getByRole("radio", { name: "Plus" }).click();
  await dialog.getByLabel(`Quantité : ${name}`).fill("2");
  await expect(dialog.getByRole("status")).toContainText("14 pièces");
  await dialog.getByRole("radio", { name: "Retrouvé" }).click();
  await dialog.getByRole("button", { name: "Valider la correction" }).click();
  await expect(page.getByText("Stock corrigé.")).toBeVisible();
  await expect(dialog).toBeHidden();
  await expect(page.getByText(/^14 pièces$/)).toBeVisible();
  await shot(page, "fiche-produit");

  // Liste : recherche, stock et statut de la page.
  await page.goto("/products");
  await page.getByRole("searchbox").fill(name);
  const row = page.getByRole("row").filter({ hasText: name });
  await expect(row).toContainText("14 pièces");
  await expect(row).toContainText("Disponible");
  await page.getByRole("searchbox").fill("");
  await expect(page.getByText(/^\d+ produits?$/)).toBeVisible();
  await shot(page, "produits");
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
  await touch(page.getByLabel(`Quantité : ${name}`).first().fill("10"));
  await touch(page.getByRole("button", { name: "Enregistrer l'article" }).click());
  expect(touches).toBeLessThan(8);

  // Référence et code-barres générés par le serveur (ADR 0066).
  await expect(page).toHaveURL(/\/products\/[0-9a-f-]+$/);
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
  await expect(page.getByText(/^10 sacs$/)).toBeVisible();
  await page.getByText("Plus d'infos").click();
  await expect(page.getByText(/^ART-\d{4,}$/)).toBeVisible();
  await expect(page.getByText(/^2\d{12}$/)).toBeVisible();
});
