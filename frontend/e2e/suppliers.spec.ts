import { expect, test, type Page } from "@playwright/test";

import { E2E, loginThroughUi, managerApi, stockedProduct } from "./fixtures";

const CAPTURES = "../docs/design/captures/phase-12";

test.describe.configure({ timeout: 90_000 });

async function login(page: Page) {
  await page.goto("/login");
  await loginThroughUi(page, E2E);
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
}

test("ajouter un fournisseur ; sa fiche dit ce qu'on lui doit et ce qu'il livre", async ({
  page,
  request,
}) => {
  const client = await managerApi(request);
  const marker = crypto.randomUUID().slice(0, 6);
  const name = `Grossiste ${marker}`;
  const product = await stockedProduct(client, { stock: "2" });
  await login(page);

  // Écran 15, ouvert depuis la liste des fournisseurs : déjà sur « Un fournisseur ».
  await page.goto("/suppliers");
  await page.getByRole("main").getByRole("link", { name: "Nouveau fournisseur" }).click();
  await expect(page.getByRole("radio", { name: "Un fournisseur" })).toBeChecked();
  await page.getByLabel("Nom du fournisseur").fill(name);
  await page.getByRole("button", { name: "Enregistrer le fournisseur" }).click();
  await expect(page.getByText("Fournisseur ajouté")).toBeVisible();

  // « Recevoir une livraison » depuis le succès : le fournisseur est déjà choisi.
  await page.getByRole("link", { name: "Recevoir une livraison" }).click();
  await expect(page.getByRole("button", { name, exact: true })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await page.getByLabel("Chercher un autre article").fill(product.name);
  await page.getByRole("button", { name: `+ ${product.name}` }).click();
  await page.getByLabel(`Quantité : ${product.name}`).fill("10");
  await page.getByLabel(`Prix d'achat (F) : ${product.name}`).fill("700");
  await page.getByRole("button", { name: "Enregistrer la livraison" }).click();
  await expect(page.getByRole("heading", { name: "Livraison enregistrée" })).toBeVisible();

  // Écran 16 : ce qu'on lui doit, ce qu'il livre, sa livraison.
  const found = await client.get(`/suppliers?search=${encodeURIComponent(name)}`);
  const supplierId = found.items[0].id as string;
  await page.goto(`/suppliers/${supplierId}`);
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
  await expect(page.getByText(/^7\s000\sF$/).first()).toBeVisible();
  await expect(page.getByText("1 article")).toBeVisible();
  await expect(page.getByRole("tabpanel")).toContainText(/Reste 7\s000\sF/);

  // « Modifier » : l'adresse attend dans « Plus d'infos », puis s'affiche sous le nom.
  await page.getByRole("link", { name: "Modifier" }).click();
  await page.getByText("Plus d'infos").click();
  await page.getByLabel("Adresse").fill("Marché Sandaga, Dakar");
  await page.getByRole("button", { name: "Enregistrer le fournisseur" }).click();
  await expect(page.getByText(/Marché Sandaga, Dakar/)).toBeVisible();
  await page.screenshot({
    path: `${CAPTURES}/fiche-fournisseur.png`,
    fullPage: true,
    animations: "disabled",
  });

  // La liste : à qui je dois.
  await page.goto("/suppliers");
  await page.getByRole("button", { name: "À qui je dois" }).click();
  await expect(page.getByRole("link", { name: new RegExp(name) })).toContainText(
    /Vous devez 7\s000\sF/,
  );
  await page.screenshot({
    path: `${CAPTURES}/fournisseurs.png`,
    fullPage: true,
    animations: "disabled",
  });
});
