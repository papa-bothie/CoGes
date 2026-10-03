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

test("catégories, création d'un produit, changement de prix, ajustement", async ({ page }) => {
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

  // Création d'un produit dans la sous-catégorie.
  await page.goto("/products/new");
  await page.getByLabel("Nom", { exact: true }).fill(name);
  await page.getByLabel("SKU", { exact: true }).fill(`SAV-${marker}`);
  await page.getByRole("combobox", { name: "Catégorie" }).click();
  await page.getByRole("option", { name: child }).click();
  await page.getByLabel("Seuil d'alerte (facultatif)").fill("5");
  await page.getByLabel("Prix de vente").fill("750");
  await page.getByLabel("Prix d'achat (facultatif)").fill("500");
  await shot(page, "produit-formulaire");
  await page.getByRole("button", { name: "Créer le produit" }).click();

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

  // Ajustement depuis la fiche : l'article est déjà choisi.
  await page.getByRole("button", { name: "Ajuster le stock" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText(name)).toBeVisible();
  await dialog.getByRole("radio", { name: "Entrée (+)" }).click();
  await dialog.getByLabel("Quantité").fill("12");
  await dialog.getByLabel(/Coût unitaire/).fill("500");
  await dialog.getByLabel("Motif (obligatoire)").fill("Stock trouvé à l'inventaire");
  await dialog.getByRole("button", { name: "Enregistrer le mouvement" }).click();
  await expect(page.getByText("Mouvement enregistré.")).toBeVisible();
  await expect(page.getByText(/^12 pièces$/)).toBeVisible();
  await shot(page, "fiche-produit");

  // Liste : recherche, stock et statut de la page.
  await page.goto("/products");
  await page.getByRole("searchbox").fill(name);
  const row = page.getByRole("row").filter({ hasText: name });
  await expect(row).toContainText("12 pièces");
  await expect(row).toContainText("Disponible");
  await page.getByRole("searchbox").fill("");
  await expect(page.getByText(/^\d+ produits?$/)).toBeVisible();
  await shot(page, "produits");
});
