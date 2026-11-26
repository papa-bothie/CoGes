import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { DEMO, loginThroughUi, managerToken, type Credentials } from "./fixtures";

/**
 * Offres Pro et Business (prompt 41, ADR 0132) : « Mon abonnement » d'une boutique en essai
 * Pro, l'import verrouillé (jamais de 403 brut), la même boutique vue par le serveur, et la
 * section « Nos offres » de la vitrine avec sa bascule annuelle.
 */
test.describe.configure({ timeout: 90_000 });

const OFFRES: Credentials = {
  slug: "offres-e2e",
  email: "gerant@offres-e2e.example.com",
  password: process.env.E2E_PASSWORD ?? "demo-coges-2026",
};

async function login(page: Page, credentials: Credentials) {
  await page.goto("/login");
  await loginThroughUi(page, credentials);
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
}

async function noAxeViolation(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(results.violations.map((violation) => violation.id)).toEqual([]);
}

async function noHorizontalScroll(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
}

test("essai Pro : Mon abonnement dit l'offre, l'échéance, les comptes et comment payer", async ({
  page,
}) => {
  await login(page, OFFRES);
  await page.goto("/settings");
  await page.getByRole("link", { name: "Mon abonnement" }).click();
  await expect(page).toHaveURL(/\/settings\/subscription$/);
  await expect(page.getByText("CoGes Pro")).toBeVisible();
  await expect(page.getByTestId("subscription-status")).toHaveText(/^Essai gratuit jusqu'au /);
  await expect(page.getByText("1 compte sur 3")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Ce qu'ajoute Business" })).toBeVisible();
  await expect(page.getByText("4 900 F")).toBeVisible();
  await expect(page.getByText("52 920 F")).toBeVisible();
  const month = page.getByRole("link", { name: "Payer 1 mois" });
  expect(decodeURIComponent((await month.getAttribute("href")) ?? "")).toContain(
    "Je veux payer CoGes Pro pour 1 mois.",
  );
  await noAxeViolation(page);
  await page.setViewportSize({ width: 360, height: 800 });
  await noHorizontalScroll(page);
});

test("essai Pro : l'import est verrouillé, jamais un 403 brut", async ({ page, request }) => {
  await login(page, OFFRES);
  await page.goto("/settings/files");
  const locked = page.getByTestId("locked-feature");
  await expect(locked).toBeVisible();
  await expect(locked.getByText("Business", { exact: true })).toBeVisible();
  await expect(locked.getByText("Disponible avec Business")).toBeVisible();
  await expect(locked.getByRole("link", { name: "Passer à Business" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Envoyer mon fichier" })).toHaveCount(0);
  await expect(page.getByText(/403|permission_denied|plan_feature_required/)).toHaveCount(0);
  // Les exports restent ouverts.
  await expect(page.getByRole("button", { name: "Préparer le fichier" })).toBeVisible();

  // Le serveur refuse de lui-même, avec son code.
  const token = await managerToken(request, OFFRES);
  const refused = await request.get("/api/v1/imports/products/template", {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(refused.status()).toBe(403);
  expect((await refused.json()).error.code).toBe("plan_feature_required");

  await noAxeViolation(page);
  await page.setViewportSize({ width: 360, height: 800 });
  await noHorizontalScroll(page);
});

test("Business (démo) : l'import est ouvert", async ({ page }) => {
  await login(page, DEMO);
  await page.goto("/settings/files");
  await expect(page.getByRole("button", { name: "Envoyer mon fichier" })).toBeVisible();
  await expect(page.getByTestId("locked-feature")).toHaveCount(0);
});

test("vitrine : Nos offres, montants du mois puis de l'année", async ({ page }) => {
  await page.goto("/");
  const section = page.locator("#offres");
  await section.scrollIntoViewIfNeeded();
  await expect(section.getByRole("heading", { name: "CoGes Pro" })).toBeVisible();
  await expect(section.getByText("4 900 F")).toBeVisible();
  await expect(section.getByText("52 920 F")).toBeHidden();
  await section.getByText("Par an (-10 %)").click();
  await expect(section.getByText("52 920 F")).toBeVisible();
  await expect(section.getByText("106 920 F")).toBeVisible();
  await expect(section.getByText("4 900 F")).toBeHidden();
  await expect(section.getByText("30 jours d'essai gratuit sur Pro")).toBeVisible();
  await page.setViewportSize({ width: 360, height: 800 });
  await noHorizontalScroll(page);
});
