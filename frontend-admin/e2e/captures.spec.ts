import { mkdirSync } from "node:fs";
import { join } from "node:path";

import { expect, test, type Page } from "@playwright/test";

/**
 * Captures de l'administration (prompt 27, D0 et D7), lancées seulement avec
 * `ADMIN_CAPTURES=avant|apres` : chaque écran en clair et en sombre (et, « après », à 360 px).
 * Rangées dans docs/design/captures/admin/<étape>/.
 */
const STAGE = process.env.ADMIN_CAPTURES;
const ADMIN = { email: "admin@e2e.example.com", password: "admin-coges-e2e-2026" };
const OUT = join(__dirname, "..", "..", "docs", "design", "captures", "admin", STAGE ?? "x");

test.skip(!STAGE, "captures à la demande : ADMIN_CAPTURES=avant|apres");

const SCREENS: { name: string; open: (page: Page) => Promise<void> }[] = [
  { name: "01-connexion", open: async (page) => void (await page.goto("/login")) },
  {
    name: "02-entreprises",
    open: async (page) => {
      await page.goto("/companies");
      await expect(page.getByRole("heading", { name: "Entreprises" })).toBeVisible();
    },
  },
  {
    name: "03-fiche",
    open: async (page) => {
      await page.goto("/companies");
      await page.getByRole("link", { name: "Parcours administration" }).first().click();
      await expect(page.getByRole("heading", { name: "Parcours administration" })).toBeVisible();
      await expect(page.getByRole("region", { name: "Abonnement" })).toContainText("Premium");
    },
  },
  {
    name: "04-statistiques",
    open: async (page) => {
      await page.goto("/stats");
      await expect(page.getByText(/paiements? enregistrés?/)).toBeVisible();
    },
  },
  {
    name: "05-systeme",
    open: async (page) => {
      await page.goto("/system");
      await expect(page.getByRole("heading", { name: "Système" })).toBeVisible();
    },
  },
  {
    name: "06-taches",
    open: async (page) => {
      await page.goto("/system/jobs");
      await expect(page.getByRole("heading", { name: "Historique des tâches" })).toBeVisible();
    },
  },
];

const EXTRA_AFTER: typeof SCREENS = [
  {
    name: "07-tableau-de-bord",
    open: async (page) => {
      await page.goto("/");
      await expect(page.getByRole("region", { name: "À traiter" })).toBeVisible();
      await expect(page.getByText(/Compté le/).first()).toBeVisible();
    },
  },
  {
    name: "08-utilisateurs",
    open: async (page) => {
      await page.goto("/users");
      await expect(page.getByText(/^\d+ comptes?$/)).toBeVisible();
    },
  },
  {
    name: "09-equipe",
    open: async (page) => {
      await page.goto("/team");
      await expect(page.getByRole("heading", { name: "Ce que peut chaque profil" })).toBeVisible();
    },
  },
  {
    name: "10-journal",
    open: async (page) => {
      await page.goto("/audit");
      await expect(page.getByText(/^\d+ lignes?$/)).toBeVisible();
    },
  },
];

async function signIn(page: Page): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("E-mail").fill(ADMIN.email);
  await page.getByLabel("Mot de passe", { exact: true }).fill(ADMIN.password);
  await page.getByRole("button", { name: "Se connecter" }).click();
  await page.waitForURL((url) => !url.pathname.startsWith("/login"));
}

const VIEWPORTS =
  STAGE === "apres"
    ? [
        { suffix: "", width: 1280, height: 800 },
        { suffix: "-mobile", width: 360, height: 760 },
      ]
    : [{ suffix: "", width: 1280, height: 800 }];

for (const scheme of ["light", "dark"] as const) {
  for (const viewport of VIEWPORTS) {
    test(`captures ${STAGE} ${scheme}${viewport.suffix}`, async ({ page }) => {
      test.setTimeout(180_000);
      mkdirSync(OUT, { recursive: true });
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.emulateMedia({ colorScheme: scheme, reducedMotion: "reduce" });
      const screens = STAGE === "apres" ? [...SCREENS, ...EXTRA_AFTER] : SCREENS;
      for (const screen of screens) {
        if (screen.name === "01-connexion") {
          await screen.open(page);
        } else {
          if (page.url().includes("/login") || page.url() === "about:blank") await signIn(page);
          await screen.open(page);
        }
        // Tout posé : profil dans le bandeau, bilan du système, données de la page.
        await page.waitForLoadState("networkidle");
        await page.screenshot({
          path: join(
            OUT,
            `${screen.name}-${scheme === "light" ? "clair" : "sombre"}${viewport.suffix}.png`,
          ),
          fullPage: true,
        });
      }
    });
  }
}
