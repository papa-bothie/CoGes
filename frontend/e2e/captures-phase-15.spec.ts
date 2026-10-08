import { expect, test, type Page } from "@playwright/test";

import { DEMO, loginThroughUi } from "./fixtures";
import { SCREENS, settle } from "./screens";

/**
 * Captures avant / après de la phase 15, en clair et en sombre
 * (docs/design/captures/phase-15/<CAPTURES_STAGE>/). Ne tourne que si `CAPTURES_STAGE` est
 * défini : `CAPTURES_STAGE=avant pnpm e2e captures-phase-15`. Lot 0 : les écrans touchés
 * par les bugs B1 à B3. `CAPTURES_LOT=F` : le thème change partout, donc tous les écrans,
 * plus la connexion, dans le sous-dossier `lot-f/`. `CAPTURES_LOT=1` : les formulaires du lot 1
 * (article, personne, stock, paiements), dialogues ouverts, dans `lot-1/`.
 */
const STAGE = process.env.CAPTURES_STAGE;
const LOT = process.env.CAPTURES_LOT ?? "0";
const LOT_0 = ["tableau-de-bord", "ventes", "vente-detail", "nouvelle-vente"];
const FOLDER = LOT === "0" ? "" : `/lot-${LOT.toLowerCase()}`;

/** Lot 1 : chaque formulaire touché, ouvert depuis son écran. Les libellés changent avec
 * le lot : chaque état cherche l'ancien libellé puis le nouveau. */
const LOT_1: { name: string; open: (page: Page) => Promise<void> }[] = [
  { name: "article-nouveau", open: (page) => page.goto("/products/new").then(() => undefined) },
  { name: "articles", open: (page) => page.goto("/products").then(() => undefined) },
  { name: "clients", open: (page) => page.goto("/customers").then(() => undefined) },
  { name: "fournisseurs", open: (page) => page.goto("/suppliers").then(() => undefined) },
  {
    name: "client-nouveau",
    open: async (page) => {
      await page.goto("/customers");
      await settle(page);
      await page.getByRole("button", { name: /Nouveau client|Ajouter une personne/ }).click();
    },
  },
  {
    name: "fournisseur-nouveau",
    open: async (page) => {
      await page.goto("/suppliers");
      await settle(page);
      await page.getByRole("button", { name: /Nouveau fournisseur|Ajouter une personne/ }).click();
    },
  },
  { name: "stock", open: (page) => page.goto("/inventory").then(() => undefined) },
  {
    name: "stock-corriger",
    open: async (page) => {
      await page.goto("/inventory");
      await settle(page);
      await page.getByRole("button", { name: /Nouveau mouvement|Corriger le stock/ }).click();
    },
  },
  {
    name: "dette-regler",
    open: async (page) => {
      await page.goto("/finance?tab=debts&party=customer&status=open");
      await settle(page);
      await page.getByRole("button", { name: "Régler" }).first().click();
    },
  },
  {
    name: "paiement-nouveau",
    open: async (page) => {
      await page.goto("/finance?tab=payments");
      await settle(page);
      await page.getByRole("button", { name: /Nouveau paiement/ }).click();
    },
  },
  {
    name: "depense-nouvelle",
    open: async (page) => {
      await page.goto("/finance?tab=expenses");
      await settle(page);
      await page.getByRole("button", { name: /Nouvelle dépense/ }).click();
    },
  },
];

test.describe("captures de la phase 15", () => {
  test.skip(!STAGE, "CAPTURES_STAGE non défini");

  for (const scheme of ["light", "dark"] as const) {
    test.describe(scheme === "light" ? "clair" : "sombre", () => {
      test.use({ colorScheme: scheme });

      async function shoot(page: Page, name: string) {
        await page.screenshot({
          path: `../docs/design/captures/phase-15/${STAGE}/${scheme}${FOLDER}/${name}.png`,
          fullPage: true,
          animations: "disabled",
        });
      }

      test("connexion", async ({ page }) => {
        test.skip(LOT === "0", "lot 0 : écran non touché");
        await page.context().clearCookies();
        await page.goto("/login");
        await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
        await page.waitForLoadState("networkidle");
        await shoot(page, "connexion");
      });

      test("vitrine des composants", async ({ page }) => {
        test.skip(LOT !== "F", "lot F seulement");
        await page.goto("/dev/composants");
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible({ timeout: 60_000 });
        await page.waitForLoadState("networkidle");
        await shoot(page, "composants");
      });

      test.beforeEach(async ({ page }, info) => {
        if (info.title === "connexion" || info.title === "vitrine des composants") return;
        await page.goto("/login");
        await loginThroughUi(page, DEMO);
        await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
      });

      test("formulaires du lot 1", async ({ page }) => {
        test.skip(LOT !== "1", "lot 1 seulement");
        test.setTimeout(400_000);
        for (const screen of LOT_1) {
          await screen.open(page);
          await settle(page);
          await shoot(page, screen.name);
          await page.keyboard.press("Escape");
        }
      });

      test("écrans du lot", async ({ page, request }) => {
        test.skip(LOT === "1", "lot 1 : formulaires seulement");
        test.setTimeout(400_000);
        const screens = LOT === "0" ? SCREENS.filter((s) => LOT_0.includes(s.name)) : SCREENS;
        for (const screen of screens) {
          await screen.open(page, request);
          await settle(page);
          await shoot(page, screen.name);
        }

        // B3 : la liste des clients ouverte, là où elle était rognée.
        await page.goto("/sales/new");
        await settle(page);
        await page.getByRole("combobox", { name: /client/i }).click();
        await expect(page.getByRole("option").first()).toBeVisible();
        await shoot(page, "nouvelle-vente-clients");
      });
    });
  }
});
