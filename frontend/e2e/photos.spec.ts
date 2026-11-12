import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { E2E, emptyMyDrafts, loginThroughUi, managerApi, stockedProduct } from "./fixtures";

/**
 * Photo d'un article (prompt 36, bloc I, ADR 0121), sur un téléphone (360 px) : « Prendre une
 * photo » depuis la fiche (le flux de la caméra arrière est remplacé par un fichier posé sur
 * le champ `capture`), la grande image sur la fiche, la vignette dans la grille de vente.
 *
 * L'API des parcours dépose chez un faux Cloudinary local (`tests/helpers/fake_cloudinary.py`) ;
 * les images de `res.cloudinary.com` sont servies ici, sans réseau.
 */
test.describe.configure({ timeout: 120_000, mode: "serial" });
test.use({ viewport: { width: 360, height: 760 } });

// Une petite image PNG (8 × 8, orange) : de quoi passer le décodage du serveur.
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAFElEQVR4nGN8ViHCgA0wYRUdtBIAJhUBgttXMZkAAAAASUVORK5CYII=",
  "base64",
);

test.beforeEach(async ({ page, request }) => {
  await emptyMyDrafts(request);
  await page.route("https://res.cloudinary.com/**", (route) =>
    route.fulfill({ status: 200, contentType: "image/png", body: PNG }),
  );
});

async function login(page: Page) {
  await page.goto("/login");
  await loginThroughUi(page, E2E);
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
}

async function noHorizontalScroll(page: Page) {
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      ),
    )
    .toBeLessThanOrEqual(0);
}

test("prendre la photo d'un article et la voir dans la grille de vente", async ({
  page,
  request,
}) => {
  const client = await managerApi(request);
  const product = await stockedProduct(client, { stock: "10", name: `Riz photo ${Date.now()}` });
  await login(page);

  await page.goto(`/products/${product.id}`);
  await expect(page.getByRole("heading", { name: "Photo de l'article" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Prendre une photo" })).toBeVisible();
  await page.getByTestId("photo-camera").setInputFiles({
    name: "camera.png",
    mimeType: "image/png",
    buffer: PNG,
  });
  await expect(page.getByText("Photo enregistrée.")).toBeVisible();

  // La grande image de la fiche vient de Cloudinary, à la bonne largeur.
  const large = page.getByRole("img", { name: `Photo de ${product.name}` }).first();
  await expect(large).toHaveAttribute("src", /^https:\/\/res\.cloudinary\.com\/coges-e2e\//);
  const stored = await client.get(`/products/${product.id}`);
  expect(stored.photo.public_id).toMatch(/^coges-(local|ci)\/[0-9a-f-]{36}\/[A-Za-z0-9_-]{22}$/);
  await noHorizontalScroll(page);
  const axe = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(axe.violations).toEqual([]);

  // Dans la grille de vente : la vignette, petite, à la place du carré coloré.
  await page.goto("/sales/new");
  await page.getByRole("searchbox", { name: "Chercher un article" }).fill(product.name);
  const tile = page.getByRole("button", { name: `Ajouter ${product.name}` });
  const thumbnail = tile.locator("img");
  await expect(thumbnail).toHaveAttribute("src", /res\.cloudinary\.com.*w_104,h_104/);
  await expect(thumbnail).toHaveAttribute("loading", "lazy");
  await noHorizontalScroll(page);
});

test("« Nouvel article » avec sa photo", async ({ page, request }) => {
  await login(page);
  await page.goto("/products/new");
  const name = `Huile photo ${Date.now()}`;
  await page.getByLabel("Nom de l'article").fill(name);
  await page.getByTestId("photo-library").setInputFiles({
    name: "huile.png",
    mimeType: "image/png",
    buffer: PNG,
  });
  await expect(
    page.getByText("La photo sera ajoutée à l'enregistrement de l'article."),
  ).toBeVisible();
  await page.getByLabel("Prix de vente (F)").fill("2500");
  await page.getByLabel("Prix d'achat (F)").fill("2000");
  await page.getByRole("button", { name: "Enregistrer l'article" }).click();
  await expect(page.getByRole("heading", { name: `${name} est ajouté` })).toBeVisible();

  const client = await managerApi(request);
  const found = await client.get(`/products?search=${encodeURIComponent(name)}`);
  expect(found.items[0].photo).not.toBeNull();
});
