import { execFileSync } from "node:child_process";

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { loginThroughUi, type Credentials } from "./fixtures";

/**
 * Relances de fin d'essai (prompt 43, ADR 0133) : la boutique `relance-e2e` voit sa fin
 * déplacée, puis la vraie tâche de nuit tourne (`e2e.sh system renewal`). Bandeau du gérant
 * la veille et au dernier rappel, jamais par-dessus la caisse, repliable pour la journée ;
 * boutique en pause à la connexion, avec WhatsApp pour payer.
 */
test.describe.configure({ mode: "serial", timeout: 90_000 });

const SHOP: Credentials = {
  slug: "relance-e2e",
  email: "gerant@relance-e2e.example.com",
  password: process.env.E2E_PASSWORD ?? "demo-coges-2026",
};

function night(day: number) {
  execFileSync("../deploy/scripts/e2e.sh", ["system", "renewal", SHOP.slug, String(day)], {
    stdio: "inherit",
  });
}

async function login(page: Page) {
  await page.goto("/login");
  await loginThroughUi(page, SHOP);
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

const banner = (page: Page) =>
  page.getByRole("status").filter({ hasText: /se termine demain|Dernier rappel/ });

test("la veille : le bandeau du gérant mène à « Mon abonnement », se replie pour la journée", async ({
  page,
}) => {
  night(-1);
  await login(page);
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
  await expect(banner(page)).toContainText(
    "Votre essai gratuit de CoGes Pro se termine demain. Pour continuer sans interruption",
  );
  await noAxeViolation(page);
  await page.setViewportSize({ width: 360, height: 800 });
  await noHorizontalScroll(page);

  await banner(page).getByRole("link", { name: "Choisir mon offre" }).click();
  await expect(page).toHaveURL(/\/settings\/subscription$/);

  await banner(page).getByRole("button", { name: "Masquer pour aujourd’hui" }).click();
  await expect(banner(page)).toHaveCount(0);
  await page.reload();
  await expect(page.getByText("CoGes Pro")).toBeVisible();
  await expect(banner(page)).toHaveCount(0);
});

test("dernier rappel : orange, dans le flux de la page, jamais par-dessus la caisse", async ({
  page,
}) => {
  night(2);
  await page.setViewportSize({ width: 360, height: 800 });
  await login(page);
  await page.goto("/sales/new");
  const last = banner(page);
  await expect(last).toContainText("sera mise en pause demain");
  await expect(last).toHaveClass(/bg-stock-teinte/);
  // Ni fixe ni collant : il pousse la page, il ne couvre ni le panier ni l'encaissement.
  expect(await last.evaluate((node) => getComputedStyle(node).position)).toBe("static");
  expect(await last.evaluate((node) => node.closest("#contenu") !== null)).toBe(true);
  await noAxeViolation(page);
  await noHorizontalScroll(page);
});

test("J+3 : la boutique est en pause, la connexion le dit avec WhatsApp pour payer", async ({
  page,
}) => {
  night(4);
  await page.setViewportSize({ width: 360, height: 800 });
  await login(page);
  const paused = page.getByRole("alert").filter({ hasText: "Votre boutique est en pause" });
  await expect(paused).toBeVisible();
  await expect(paused).toContainText("Vos ventes, votre stock et vos clients sont gardés");
  const whatsapp = paused.getByRole("link", { name: "Payer sur WhatsApp" });
  const href = new URL((await whatsapp.getAttribute("href")) ?? "");
  expect(href.hostname).toBe("wa.me");
  expect(href.searchParams.get("text")).toContain("relance-e2e");
  await expect(page).toHaveURL(/\/login/);
  await noAxeViolation(page);
  await noHorizontalScroll(page);
});
