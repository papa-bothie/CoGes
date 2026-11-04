import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { E2E, emptyMyDrafts, loginThroughUi, managerApi, stockedProduct } from "./fixtures";

/**
 * Deux articles de même nom, distingués par leur description (ADR 0108, correction du
 * 2026-11-04) : grille et recherche de Vendre, ticket, Stock, livraison.
 */
test.describe.configure({ timeout: 120_000, mode: "serial" });

test.beforeEach(async ({ request }) => {
  await emptyMyDrafts(request);
});

async function login(page: Page) {
  await page.goto("/login");
  await loginThroughUi(page, E2E);
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
}

async function noViolation(page: Page) {
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();
    expect(results.violations, scheme).toEqual([]);
  }
  await page.emulateMedia({ colorScheme: "light" });
}

async function noHorizontalScroll(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
}

test("deux « Huile » : le vendeur les distingue partout et « 5 litres » trouve la bonne", async ({
  page,
  request,
}) => {
  const client = await managerApi(request);
  const name = `Huile ${crypto.randomUUID().slice(0, 6)}`;
  const small = await stockedProduct(client, {
    stock: "10",
    price: "1500",
    name,
    description: "1 litre",
  });
  const large = await stockedProduct(client, {
    stock: "10",
    price: "1500",
    name,
    description: "5 litres",
  });
  await login(page);

  // Grille : les deux tuiles portent leur description, et leur nom accessible aussi.
  await page.goto("/sales/new");
  const search = page.getByRole("searchbox", { name: "Chercher un article" });
  await search.fill(name);
  await expect(page.getByRole("button", { name: new RegExp(`^Ajouter ${name}`) })).toHaveCount(2);
  const smallTile = page.getByRole("button", { name: `Ajouter ${name}, 1 litre` });
  const largeTile = page.getByRole("button", { name: `Ajouter ${name}, 5 litres` });
  await expect(smallTile).toContainText("1 litre");
  await expect(largeTile).toContainText("5 litres");

  // Recherche par la description : seule la bonne reste.
  await search.fill("5 litres");
  await expect(largeTile).toBeVisible();
  await expect(smallTile).toHaveCount(0);
  await largeTile.click();

  // Ticket : la ligne dit laquelle est au panier.
  const ticketHint = page.getByRole("button", {
    name: `Lire toute la description de ${name} : 5 litres`,
  });
  await expect(ticketHint).toBeVisible();
  await noViolation(page);
  await page.setViewportSize({ width: 360, height: 780 });
  await expect(ticketHint).toBeVisible();
  await noHorizontalScroll(page);
  await page.setViewportSize({ width: 1280, height: 900 });

  // Stock : les deux lignes, chacune avec sa description.
  await page.goto(`/products?search=${encodeURIComponent(name)}`);
  const rows = page.getByRole("link", { name: new RegExp(name) });
  await expect(rows).toHaveCount(2);
  await expect(page.getByRole("link", { name: new RegExp(`${name}.*1 litre`) })).toHaveAttribute(
    "href",
    `/products/${small.id}`,
  );
  await expect(page.getByRole("link", { name: new RegExp(`${name}.*5 litres`) })).toHaveAttribute(
    "href",
    `/products/${large.id}`,
  );
  await page.getByRole("searchbox").fill("5 litres");
  await expect(page.getByRole("link", { name: new RegExp(`${name}.*5 litres`) })).toBeVisible();
  await expect(page.getByRole("link", { name: new RegExp(`${name}.*1 litre\\b`) })).toHaveCount(0);
  await noViolation(page);
  await page.setViewportSize({ width: 360, height: 780 });
  await noHorizontalScroll(page);
  await page.setViewportSize({ width: 1280, height: 900 });

  // Livraison : les résultats de la recherche portent aussi la description.
  await page.goto("/inventory/receive");
  await page.getByRole("searchbox", { name: "Chercher un autre article" }).fill(name);
  await expect(
    page.getByRole("button", { name: new RegExp(`\\+ ${name}.*1 litre`) }),
  ).toBeVisible();
  await page.getByRole("button", { name: new RegExp(`\\+ ${name}.*5 litres`) }).click();
  await expect(
    page.getByRole("button", { name: `Lire toute la description de ${name} : 5 litres` }),
  ).toBeVisible();
});

test("deux homonymes sans description : la référence les distingue", async ({ page, request }) => {
  const client = await managerApi(request);
  const name = `Savon ${crypto.randomUUID().slice(0, 6)}`;
  const first = await stockedProduct(client, { stock: "5", name });
  const second = await stockedProduct(client, { stock: "5", name });
  await login(page);
  await page.goto("/sales/new");
  await page.getByRole("searchbox", { name: "Chercher un article" }).fill(name);
  await expect(
    page.getByRole("button", { name: `Ajouter ${name}, Réf. ${first.sku}` }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: `Ajouter ${name}, Réf. ${second.sku}` }),
  ).toBeVisible();
});

test("un article sans description n'a pas de ligne en plus", async ({ page, request }) => {
  const client = await managerApi(request);
  const product = await stockedProduct(client, { stock: "5" });
  await login(page);
  await page.goto("/sales/new");
  await page.getByRole("searchbox", { name: "Chercher un article" }).fill(product.name);
  const tile = page.getByRole("button", { name: `Ajouter ${product.name}`, exact: true });
  await expect(tile).toBeVisible();
  await expect(tile.locator('[data-slot="product-hint"]')).toHaveCount(0);
});
