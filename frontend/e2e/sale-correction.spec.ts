import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import {
  createSalesperson,
  loginThroughUi,
  managerApi,
  stockedProduct,
  type Credentials,
} from "./fixtures";

/**
 * « Corriger cette vente » (prompt 36, bloc R, ADR 0119), de bout en bout sur un téléphone :
 * un vendeur encaisse 2 articles, se rend compte qu'il n'en fallait qu'un, corrige depuis
 * l'écran de succès, réencaisse. La caisse du jour ne garde que le second encaissement ;
 * l'ancienne vente dit qu'elle est corrigée et par quelle vente.
 */
test.describe.configure({ timeout: 120_000, mode: "serial" });
test.use({ viewport: { width: 360, height: 760 } });

async function login(page: Page, who: Credentials) {
  await page.goto("/login");
  await loginThroughUi(page, who);
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

async function axe(page: Page) {
  const result = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(result.violations).toEqual([]);
}

test("un vendeur corrige une vente encaissée puis la réencaisse, la caisse reste juste", async ({
  page,
  request,
}) => {
  const client = await managerApi(request);
  const product = await stockedProduct(client, { stock: "10" });
  const cashBefore = Number((await client.get("/analytics/cash")).net_cash);

  await login(page, await createSalesperson(request));
  await page.goto("/sales/new");
  await page.getByRole("searchbox", { name: "Chercher un article" }).fill(product.name);
  await page.getByRole("button", { name: `Ajouter ${product.name}` }).click();
  await page.getByRole("button", { name: `Ajouter ${product.name}` }).click();
  await expect(page.getByRole("textbox", { name: `Quantité de ${product.name}` })).toHaveValue("2");
  await page.waitForLoadState("networkidle");
  await page.getByRole("button", { name: /^Encaisser 2\s000\sF$/ }).click();
  await expect(page.getByRole("heading", { name: "Vente enregistrée" })).toBeVisible();

  // L'éditeur a déjà réécrit l'adresse en `/sales/{vente}/edit` : la vente se lit au reçu.
  const receipt = await page.getByRole("link", { name: "Imprimer le reçu" }).getAttribute("href");
  const saleId = receipt!.split("/")[2] ?? "";
  expect(saleId).not.toBe("");

  // Le bouton dit le temps qui reste, à l'heure du serveur.
  const correct = page.getByRole("button", { name: /Corriger cette vente/ });
  await expect(correct).toContainText(/encore (10|9) min/);
  await noHorizontalScroll(page);
  await correct.click();
  await expect(
    page.getByText(
      /La vente n° \d+ sera annulée\. Vous la referez, puis vous encaisserez de nouveau\./,
    ),
  ).toBeVisible();
  await axe(page);
  await page.getByRole("button", { name: "Oui, corriger" }).click();

  // Le brouillon de la correction s'ouvre, avec le même article.
  await expect(page).toHaveURL(
    (url) => /\/sales\/[0-9a-f-]+\/edit$/.test(url.pathname) && !url.pathname.includes(saleId),
    { timeout: 30_000 },
  );
  await expect(page.getByText(/Correction de la vente n° \d+, annulée\./)).toBeVisible();
  const quantity = page.getByRole("textbox", { name: `Quantité de ${product.name}` });
  await expect(quantity).toHaveValue("2");
  await quantity.fill("1");
  await quantity.press("Enter");
  await expect(quantity).toHaveValue("1");
  await page.waitForLoadState("networkidle");
  await page.getByRole("button", { name: /^Encaisser 1\s000\sF$/ }).click();
  await expect(page.getByRole("heading", { name: "Vente enregistrée" })).toBeVisible();

  // Caisse du jour : 1 000 de plus, pas 3 000.
  const cash = await client.get("/analytics/cash");
  expect(Number(cash.net_cash)).toBe(cashBefore + 1000);
  const marked = (cash.lines as { correction: boolean; is_reversal: boolean }[]).filter(
    (line) => line.correction,
  );
  expect(marked.some((line) => line.is_reversal)).toBe(true);
  expect(marked.some((line) => !line.is_reversal)).toBe(true);

  // L'ancienne vente dit qu'elle est corrigée, et par quelle vente.
  await page.goto(`/sales/${saleId}`);
  await expect(page.getByText(/Corrigée — remplacée par la vente n° \d+\./)).toBeVisible();
  await expect(page.getByRole("button", { name: /Corriger cette vente/ })).toHaveCount(0);
  await noHorizontalScroll(page);
  await axe(page);
});
