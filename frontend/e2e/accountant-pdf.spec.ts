import { execFileSync } from "node:child_process";

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { E2E, loginThroughUi, managerApi, stockedProduct } from "./fixtures";

/**
 * Exports PDF pour le comptable (prompt 35, bloc X, ADR 0114) : les ventes du mois de
 * bout en bout (demande sur l'écran Argent, fichier produit comme par le worker, prêt dans
 * Réglages → Fichiers, téléchargé), l'état du stock immédiat, axe en clair et en sombre,
 * 360 px.
 */
test.describe.configure({ timeout: 150_000, mode: "serial" });

async function login(page: Page) {
  await page.goto("/login");
  await loginThroughUi(page, E2E);
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
}

async function noViolation(page: Page) {
  await page.mouse.move(0, 0);
  await expect(page.locator("[data-sonner-toast]")).toHaveCount(0, { timeout: 15_000 });
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();
    expect(results.violations, scheme).toEqual([]);
  }
  await page.emulateMedia({ colorScheme: "light" });
}

async function pdfOf(
  page: Page,
  click: () => Promise<void>,
): Promise<{ name: string; head: string }> {
  const [download] = await Promise.all([page.waitForEvent("download"), click()]);
  const chunks: Buffer[] = [];
  for await (const chunk of await download.createReadStream()) chunks.push(Buffer.from(chunk));
  return {
    name: download.suggestedFilename(),
    head: Buffer.concat(chunks).subarray(0, 5).toString(),
  };
}

test.beforeAll(async ({ request }) => {
  // Une vente du jour, pour que le document du mois ne soit pas vide.
  const client = await managerApi(request);
  const product = await stockedProduct(client, { stock: "5", price: "2500" });
  const sale = await client.post("/sales", {});
  await client.post(`/sales/${sale.id}/items`, { product_id: product.id, qty: "1" });
  await client.post(`/sales/${sale.id}/confirm`, { paid_amount: "2500", method: "cash" });
});

test("les ventes du mois en PDF, de l'écran Argent à Réglages → Fichiers", async ({ page }) => {
  await login(page);
  await page.goto("/finance");
  const section = page.getByRole("region", { name: "Pour votre comptable" });
  await expect(section).toBeVisible();
  const sales = section.locator("div", { hasText: "Ventes sur une période" }).last();
  await sales.getByRole("button", { name: "Exporter en PDF" }).click();
  await sales.getByRole("button", { name: "Ce mois" }).click();
  await sales.getByRole("button", { name: "Préparer le PDF" }).click();
  await expect(sales.getByRole("status")).toContainText("Le PDF est en préparation");
  await noViolation(page);

  execFileSync("../deploy/scripts/e2e.sh", ["system", "build-exports"], { stdio: "inherit" });

  await sales.getByRole("link", { name: "Réglages → Fichiers" }).click();
  await expect(page).toHaveURL(/\/settings\/files$/);
  const row = page
    .getByRole("listitem")
    .filter({ hasText: /Ventes d.+ · PDF/ })
    .first();
  await expect(row).toBeVisible({ timeout: 15_000 });
  const file = await pdfOf(page, () => row.getByRole("button", { name: "Télécharger" }).click());
  expect(file.name).toMatch(/^Ventes-\d{4}-\d{2}-\d{2}-au-\d{4}-\d{2}-\d{2}-.+\.pdf$/);
  expect(file.head).toBe("%PDF-");
});

test("l'état du stock se télécharge tout de suite", async ({ page }) => {
  await login(page);
  await page.goto("/products");
  const section = page.getByRole("region", { name: "Pour votre comptable" });
  const file = await pdfOf(page, () =>
    section.getByRole("button", { name: "Exporter en PDF" }).click(),
  );
  expect(file.name).toMatch(/^Stock-\d{4}-\d{2}-\d{2}-.+\.pdf$/);
  expect(file.head).toBe("%PDF-");
});

test("à 360 px, le bloc du comptable tient sans défilement horizontal", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 780 });
  await login(page);
  await page.goto("/finance/cash");
  const section = page.getByRole("region", { name: "Pour votre comptable" });
  await section.getByRole("button", { name: "Exporter en PDF" }).click();
  await section.getByRole("button", { name: "Choisir des dates" }).click();
  await expect(section.getByLabel("Du")).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
  await noViolation(page);
});
