import { execFileSync } from "node:child_process";

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { ADMIN, enterCode } from "./mfa";

/**
 * « À relancer » et « Prolonger » (prompt 43, ADR 0133) sur `relance-e2e`, créée par
 * `e2e.sh reset` ; `e2e.sh system renewal` déplace sa fin et fait tourner la nuit.
 */
test.describe.configure({ timeout: 90_000 });

function night(day: number): void {
  execFileSync("../deploy/scripts/e2e.sh", ["system", "renewal", "relance-e2e", String(day)], {
    stdio: "inherit",
  });
}

async function signIn(page: Page): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("E-mail").fill(ADMIN.email);
  await page.getByLabel("Mot de passe", { exact: true }).fill(ADMIN.password);
  await page.getByRole("button", { name: "Se connecter" }).click();
  await enterCode(page);
  await expect(page.getByRole("heading", { name: "Tableau de bord" })).toBeVisible();
}

async function axe(page: Page): Promise<void> {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  expect(results.violations).toEqual([]);
}

test("À relancer : l'étape, WhatsApp prérempli, puis Prolonger remet le calendrier à zéro", async ({
  page,
}) => {
  night(2);
  await signIn(page);
  await expect(page.getByRole("link", { name: /boutiques? à relancer/ })).toBeVisible();
  await page.getByRole("link", { name: "À relancer" }).first().click();
  await expect(page.getByRole("heading", { name: "À relancer", level: 1 })).toBeVisible();

  const card = page.getByRole("region", { name: "Parcours relances" });
  await expect(card.getByText("Dernier rappel", { exact: true })).toBeVisible();
  await expect(card).toContainText("Déjà envoyé : dernier rappel");
  const whatsapp = card.getByRole("link", { name: /Écrire sur WhatsApp/ });
  const href = new URL((await whatsapp.getAttribute("href")) ?? "");
  expect(href.hostname).toBe("wa.me");
  expect(href.searchParams.get("text")).toContain("sera mise en pause demain");
  await axe(page);
  await page.setViewportSize({ width: 360, height: 800 });
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
  await page.setViewportSize({ width: 1280, height: 900 });

  await card.getByRole("link", { name: "Parcours relances" }).click();
  const subscription = page.getByRole("region", { name: "Abonnement" });
  await expect(subscription.getByTestId("relance-etape")).toContainText("Dernier rappel");
  await subscription.getByLabel("Jours").fill("10");
  await subscription.getByLabel("Raison de la prolongation").fill("Paiement promis lundi");
  await subscription.getByRole("button", { name: "Prolonger" }).click();
  await expect(subscription.getByRole("status")).toContainText("Prolongé de 10 jours");
  await expect(subscription.getByTestId("relance-etape")).toHaveText(
    "Aucune relance pour cette fin",
  );
  await axe(page);
});
