import { execFileSync } from "node:child_process";

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { ADMIN, enterCode } from "./mfa";

/**
 * Surveillance web (ADR 0090). L'API des parcours tourne sans worker ni relais :
 * `e2e.sh system healthy` écrit ce qu'ils écriraient, `missing-heartbeat` retire le
 * battement du worker. Seulement sur coges_e2e et un Redis local.
 */

function systemState(state: "healthy" | "missing-heartbeat"): void {
  execFileSync("../deploy/scripts/e2e.sh", ["system", state], { stdio: "inherit" });
}

async function signIn(page: Page): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("E-mail").fill(ADMIN.email);
  await page.getByLabel("Mot de passe", { exact: true }).fill(ADMIN.password);
  await page.getByRole("button", { name: "Se connecter" }).click();
  await enterCode(page);
  await expect(page.getByRole("heading", { name: "Tableau de bord" })).toBeVisible();
  await page.goto("/companies");
}

async function axe(page: Page): Promise<void> {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  expect(results.violations).toEqual([]);
}

/** Next annonce les changements de route dans un `alert` vide : on vise le bandeau. */
function banner(page: Page) {
  return page.getByRole("alert").filter({ hasText: "Le système est en panne." });
}

test("système sain : pas de bandeau, tout est vert, l'historique montre l'échec rattrapé", async ({
  page,
}) => {
  systemState("healthy");
  await signIn(page);
  await page.getByRole("link", { name: "Système", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Système" })).toBeVisible();
  await expect(page.getByText("Tout fonctionne")).toBeVisible();
  await expect(page.getByText(/Vérifié à \d\d:\d\d:\d\d/)).toBeVisible();
  await expect(page.getByText("Aucun événement au rebut.")).toBeVisible();
  await expect(banner(page)).toHaveCount(0);
  await axe(page);

  await page.getByRole("link", { name: "Historique des tâches" }).click();
  await expect(page.getByRole("heading", { name: "Historique des tâches" })).toBeVisible();
  await page.getByLabel("Statut").selectOption("failed");
  await expect(page.getByText("1 exécution", { exact: true })).toBeVisible();
  await page.getByRole("row", { name: /Recalcul du stock/ }).click();
  await expect(page.getByText("OperationalError (08006)")).toBeVisible();
  await axe(page);
});

test("battement manquant : le bandeau rouge est sur toutes les pages, pas seulement Système", async ({
  page,
}) => {
  systemState("healthy");
  systemState("missing-heartbeat");
  await signIn(page);

  // Entreprises : l'écran d'arrivée.
  await expect(banner(page)).toContainText("Battement absent : Worker (tâches)");
  await expect(banner(page)).toContainText("(heartbeat_missing:worker)");
  await axe(page);

  // Une fiche d'entreprise.
  await page.getByLabel("Nom ou code").fill("admin-e2e");
  await page.getByRole("button", { name: "Chercher" }).click();
  await page.getByRole("link", { name: "Parcours administration" }).click();
  await expect(page.getByRole("heading", { name: "Parcours administration" })).toBeVisible();
  await expect(banner(page)).toBeVisible();

  // L'historique, puis Système, qui dit où est la panne.
  await page.getByRole("link", { name: "Tâches", exact: true }).click();
  await expect(banner(page)).toBeVisible();
  await banner(page).getByRole("link", { name: "Voir l'état du système" }).click();
  await expect(page.getByText("Au moins un problème")).toBeVisible();
  await expect(
    page.getByRole("listitem").filter({ hasText: "Worker (tâches)" }).getByText("En panne"),
  ).toBeVisible();
  await axe(page);

  // Le battement revient : au prochain bilan, le bandeau s'en va.
  systemState("healthy");
  await page.getByRole("button", { name: "Actualiser" }).click();
  await expect(banner(page)).toHaveCount(0);
});
