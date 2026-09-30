import { expect, type APIRequestContext, type Page } from "@playwright/test";

import { managerApi } from "./fixtures";

/**
 * Écrans de référence de la phase 14 (captures avant / après et contrôle axe), sur le jeu de
 * démonstration. `open` mène à l'écran ; l'attente commune (`settle`) vérifie qu'il est chargé.
 */
export type Screen = {
  name: string;
  open: (page: Page, request: APIRequestContext) => Promise<void>;
};

async function firstId(request: APIRequestContext, path: string): Promise<string> {
  const api = await managerApi(request);
  const page = await api.get(`${path}${path.includes("?") ? "&" : "?"}page_size=1`);
  return page.items[0].id as string;
}

export async function settle(page: Page) {
  // Un dialogue ouvert masque la page (aria-hidden) : on attend alors son propre titre.
  const dialog = page.getByRole("dialog");
  const heading = (await dialog.isVisible())
    ? dialog.getByRole("heading").first()
    : page.getByRole("heading", { level: 1 }).first();
  await expect(heading).toBeVisible({ timeout: 30_000 });
  await page.waitForLoadState("networkidle");
  await expect(page.locator('[data-slot="skeleton"]')).toHaveCount(0, { timeout: 30_000 });
}

export const SCREENS: Screen[] = [
  { name: "tableau-de-bord", open: (page) => page.goto("/dashboard").then(() => undefined) },
  { name: "ventes", open: (page) => page.goto("/sales").then(() => undefined) },
  { name: "nouvelle-vente", open: (page) => page.goto("/sales/new").then(() => undefined) },
  {
    name: "vente-detail",
    open: async (page, request) => {
      await page.goto(`/sales/${await firstId(request, "/sales?status=confirmed")}`);
    },
  },
  { name: "stock", open: (page) => page.goto("/inventory").then(() => undefined) },
  { name: "produits", open: (page) => page.goto("/products").then(() => undefined) },
  {
    name: "produit-detail",
    open: async (page, request) => {
      await page.goto(`/products/${await firstId(request, "/products")}`);
    },
  },
  { name: "clients", open: (page) => page.goto("/customers").then(() => undefined) },
  { name: "fournisseurs", open: (page) => page.goto("/suppliers").then(() => undefined) },
  { name: "finance", open: (page) => page.goto("/finance").then(() => undefined) },
  { name: "analytics", open: (page) => page.goto("/analytics").then(() => undefined) },
  { name: "intelligence", open: (page) => page.goto("/insights?status=all").then(() => undefined) },
  {
    name: "intelligence-panneau",
    open: async (page) => {
      await page.goto("/insights?status=all");
      const card = page.getByRole("main").getByRole("listitem").first().getByRole("button");
      await expect(card).toBeVisible({ timeout: 30_000 });
      await card.click();
      await expect(page.getByRole("dialog")).toBeVisible();
    },
  },
  { name: "parametres", open: (page) => page.goto("/settings").then(() => undefined) },
  { name: "notifications", open: (page) => page.goto("/notifications").then(() => undefined) },
];
