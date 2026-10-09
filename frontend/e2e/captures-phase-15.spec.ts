import { expect, test, type Page } from "@playwright/test";

import { DEMO, loginThroughUi } from "./fixtures";
import { SCREENS, settle } from "./screens";

/**
 * Captures avant / après de la phase 15, en clair et en sombre
 * (docs/design/captures/phase-15/<CAPTURES_STAGE>/). Ne tourne que si `CAPTURES_STAGE` est
 * défini : `CAPTURES_STAGE=avant pnpm e2e captures-phase-15`. Lot 0 : les écrans touchés
 * par les bugs B1 à B3. `CAPTURES_LOT=F` : le thème change partout, donc tous les écrans,
 * plus la connexion, dans le sous-dossier `lot-f/`. `CAPTURES_LOT=1` : les formulaires du lot 1
 * (article, personne, stock, paiements), dialogues ouverts, dans `lot-1/`. `CAPTURES_LOT=2` :
 * les écrans dont les mots changent (chiffres, stock, argent, Intelligence), dans `lot-2/`.
 * `CAPTURES_LOT=3a` : accueil et écrans de vente (maquette 01 à 06), aussi à 390 px, dans `lot-3a/`.
 */
const STAGE = process.env.CAPTURES_STAGE;
const LOT = process.env.CAPTURES_LOT ?? "0";
const LOT_0 = ["tableau-de-bord", "ventes", "vente-detail", "nouvelle-vente"];
const LOT_2 = [
  "tableau-de-bord",
  "ventes",
  "vente-detail",
  "stock",
  "produit-detail",
  "finance",
  "analytics",
  "intelligence",
  "intelligence-panneau",
];
const LOT_3A = ["tableau-de-bord", "ventes", "nouvelle-vente", "vente-detail"];
const LOT_3B = ["produits", "produit-detail", "stock"];
/** Lot 3b : pages sans entrée dans `SCREENS`. */
const LOT_3B_PAGES = [
  { name: "article-nouveau", path: "/products/new" },
  { name: "rayons", path: "/products/categories" },
];
/** Lot 3a : les pages d'une vente confirmée (reçu, retour), relatives à sa fiche. */
const LOT_3A_SALE_PAGES = [
  { name: "vente-recu", suffix: "/receipt" },
  { name: "vente-retour", suffix: "/returns/new" },
];
/** Lot 2 : les onglets de « L'argent » dont les colonnes changent de nom. */
const LOT_2_TABS = ["payments", "debts", "expenses"];
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
        const chosen = { "0": LOT_0, "2": LOT_2, "3a": LOT_3A, "3b": LOT_3B }[LOT] ?? null;
        const screens = chosen ? SCREENS.filter((s) => chosen.includes(s.name)) : SCREENS;
        for (const screen of screens) {
          await screen.open(page, request);
          await settle(page);
          await shoot(page, screen.name);
        }
        if (LOT === "3a") {
          const saleUrl = page.url();
          for (const extra of LOT_3A_SALE_PAGES) {
            await page.goto(`${saleUrl}${extra.suffix}`);
            // Le reçu d'avant n'a pas de titre de niveau 1 : on attend la fin du chargement.
            await expect(page.getByRole("main")).toBeVisible({ timeout: 30_000 });
            await page.waitForLoadState("networkidle");
            await shoot(page, extra.name);
          }
          // Téléphone (maquette 26) : les mêmes écrans à 390 px.
          await page.setViewportSize({ width: 390, height: 844 });
          for (const screen of screens) {
            await screen.open(page, request);
            await settle(page);
            await shoot(page, `${screen.name}-390`);
          }
          return;
        }
        if (LOT === "3b") {
          for (const width of [1280, 390]) {
            await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
            const suffix = width === 390 ? "-390" : "";
            if (width === 390) {
              for (const screen of screens) {
                await screen.open(page, request);
                await settle(page);
                await shoot(page, `${screen.name}${suffix}`);
              }
            }
            for (const extra of LOT_3B_PAGES) {
              await page.goto(extra.path);
              await settle(page);
              await shoot(page, `${extra.name}${suffix}`);
            }
          }
          return;
        }
        if (LOT === "2") {
          for (const tab of LOT_2_TABS) {
            await page.goto(`/finance?tab=${tab}`);
            await settle(page);
            await shoot(page, `finance-${tab}`);
          }
          return;
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
