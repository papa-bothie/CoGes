import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { E2E, loginThroughUi, managerToken } from "./fixtures";

/**
 * Logo de la boutique (prompt 35, bloc L, ADR 0111) : Réglages → Boutique, ajouter, changer,
 * retirer ; un SVG refusé ; axe en clair et en sombre ; 360 px.
 */
test.describe.configure({ timeout: 90_000, mode: "serial" });

// Deux PNG de 2 × 1 px, de couleurs différentes.
const RED = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAIAAAABCAIAAAB7QOjdAAAAD0lEQVR4nGM8wcDAwMAAAAS+AMq34uUzAAAAAElFTkSuQmCC",
  "base64",
);
const BLUE = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAIAAAABCAIAAAB7QOjdAAAAD0lEQVR4nGNkYDjBwMAAAAMuAMrJQvQuAAAAAElFTkSuQmCC",
  "base64",
);

async function removeLogo(request: APIRequestContext) {
  const token = await managerToken(request, E2E);
  const response = await request.delete("/api/v1/companies/me/logo", {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect([204, 404]).toContain(response.status());
}

async function openShop(page: Page) {
  await page.goto("/login");
  await loginThroughUi(page, E2E);
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "Logo de la boutique" })).toBeVisible();
}

async function noViolation(page: Page) {
  // L'état de repos est mesuré : aucun bouton survolé, aucun toast affiché (le toast de
  // succès `richColors` est mesuré à part, voir le résumé du bloc L).
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

test.beforeEach(async ({ request }) => removeLogo(request));
test.afterAll(async ({ request }) => removeLogo(request));

test("ajouter, changer puis retirer le logo", async ({ page }) => {
  await openShop(page);
  await expect(page.getByText("Pas encore de logo.")).toBeVisible();
  const input = page.locator('input[type="file"]');

  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Ajouter le logo" }).click();
  await (await chooser).setFiles({ name: "logo.png", mimeType: "image/png", buffer: RED });
  await expect(page.getByText("Logo enregistré.")).toBeVisible();
  const preview = page.getByRole("img", { name: "Logo de la boutique" });
  await expect(preview).toHaveAttribute("src", /^data:image\/png;base64,/);
  const first = await preview.getAttribute("src");

  await input.setInputFiles({ name: "autre.png", mimeType: "image/png", buffer: BLUE });
  await expect.poll(() => preview.getAttribute("src")).not.toBe(first);
  await noViolation(page);

  await page.getByRole("button", { name: "Retirer" }).click();
  await expect(page.getByText("Logo retiré.")).toBeVisible();
  await expect(page.getByText("Pas encore de logo.")).toBeVisible();
  await expect(preview).toHaveCount(0);
});

test("un SVG est refusé avec un message clair, sans rien envoyer", async ({ page }) => {
  await openShop(page);
  let sent = false;
  page.on("request", (request) => {
    if (request.url().endsWith("/companies/me/logo") && request.method() === "PUT") sent = true;
  });
  await page.locator('input[type="file"]').setInputFiles({
    name: "logo.svg",
    mimeType: "image/svg+xml",
    buffer: Buffer.from('<svg xmlns="http://www.w3.org/2000/svg"/>'),
  });
  await expect(page.getByText("Format non pris en charge : PNG, JPEG ou WebP.")).toBeVisible();
  expect(sent).toBe(false);
});

test("à 360 px, le bloc logo tient sans défilement horizontal", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 780 });
  await openShop(page);
  await page.locator('input[type="file"]').setInputFiles({
    name: "logo.png",
    mimeType: "image/png",
    buffer: RED,
  });
  await expect(page.getByRole("img", { name: "Logo de la boutique" })).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
  await noViolation(page);
});
