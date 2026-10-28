import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import {
  customerWithCredit,
  E2E,
  emptyMyDrafts,
  loginThroughUi,
  managerApi,
  stockedProduct,
} from "./fixtures";

/**
 * « Dernières ventes » sur l'écran Vendre (prompt 28, C4, ADR 0100) : une vente confirmée
 * apparaît en tête, une vente annulée se lit en mots, rien ne pousse le panier hors de
 * l'écran, et la page tient à 360 px.
 */
test.describe.configure({ timeout: 90_000, mode: "serial" });

test.beforeEach(async ({ request }) => {
  await emptyMyDrafts(request);
});

async function login(page: Page) {
  await page.goto("/login");
  await loginThroughUi(page, E2E);
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
}

const recent = (page: Page) =>
  page.locator("section").filter({ has: page.getByRole("button", { name: "Dernières ventes" }) });

test("confirmer une vente la fait apparaître en tête des dernières ventes", async ({
  page,
  request,
}) => {
  const client = await managerApi(request);
  const product = await stockedProduct(client, { stock: "10" });
  // Une vente annulée juste avant : elle se lit « Annulée », pas seulement en gris.
  const customer = await customerWithCredit(client);
  const cancelled = await client.post("/sales", { customer_id: customer.id });
  await client.post(`/sales/${cancelled.id}/items`, { product_id: product.id, qty: "1" });
  await client.post(`/sales/${cancelled.id}/confirm`, { paid_amount: "0", method: "cash" });
  await client.post(`/sales/${cancelled.id}/cancel`, { reason: "Erreur de saisie" });
  await login(page);

  await page.goto("/sales/new");
  const block = recent(page);
  await expect(block.getByRole("listitem").first()).toContainText("Annulée");

  await page.getByRole("searchbox", { name: "Chercher un article" }).fill(product.name);
  await page.getByRole("button", { name: `Ajouter ${product.name}` }).click();
  await expect(page.getByRole("textbox", { name: `Quantité de ${product.name}` })).toBeVisible();
  await page.waitForLoadState("networkidle");
  await page.getByRole("button", { name: /^Encaisser 1\s000\sF$/ }).click();
  await expect(page.getByRole("heading", { name: "Vente enregistrée" })).toBeVisible();
  await page.getByRole("button", { name: "Nouvelle vente" }).click();

  const first = recent(page).getByRole("listitem").first();
  await expect(first).toContainText("Client de passage");
  await expect(first).toContainText(/1\s000\sF/);
  await expect(first).toContainText("Payé");
  await first.getByRole("link").click();
  await expect(page).toHaveURL(/\/sales\/[0-9a-f-]+$/);
});

test("Vendre : axe sans violation, 360 px sans défilement, le bouton d'encaissement d'abord", async ({
  page,
}) => {
  await login(page);
  await page.goto("/sales/new");
  await expect(recent(page).getByRole("listitem").first()).toBeVisible();
  const axe = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(axe.violations).toEqual([]);

  await page.setViewportSize({ width: 360, height: 760 });
  await page.waitForLoadState("networkidle");
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      ),
    )
    .toBeLessThanOrEqual(0);
  // Sous le panier sur téléphone : le bloc vient après le bouton d'encaissement.
  const pay = await page.getByRole("button", { name: /^Encaisser/ }).boundingBox();
  const block = await recent(page).boundingBox();
  expect(pay && block && block.y > pay.y).toBe(true);
  // Repliable.
  const toggle = page.getByRole("button", { name: "Dernières ventes" });
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
});
