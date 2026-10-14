import { expect, type APIRequestContext, type Page } from "@playwright/test";

import { DEMO, managerApi } from "./fixtures";

/**
 * Écrans de référence de la phase 14 (captures avant / après et contrôle axe), sur le jeu de
 * démonstration. `open` mène à l'écran ; l'attente commune (`settle`) vérifie qu'il est chargé.
 */
export type Screen = {
  name: string;
  open: (page: Page, request: APIRequestContext) => Promise<void>;
};

async function firstId(request: APIRequestContext, path: string): Promise<string> {
  const api = await managerApi(request, DEMO);
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
  {
    name: "stock-correction",
    open: (page) => page.goto("/inventory/adjust").then(() => undefined),
  },
  {
    name: "stock-livraison",
    open: (page) => page.goto("/inventory/receive").then(() => undefined),
  },
  { name: "rayons", open: (page) => page.goto("/products/categories").then(() => undefined) },
  { name: "nouvel-article", open: (page) => page.goto("/products/new").then(() => undefined) },
  { name: "produits", open: (page) => page.goto("/products").then(() => undefined) },
  {
    name: "produit-detail",
    open: async (page, request) => {
      await page.goto(`/products/${await firstId(request, "/products")}`);
    },
  },
  { name: "clients", open: (page) => page.goto("/customers").then(() => undefined) },
  {
    name: "fiche-client",
    open: async (page, request) => {
      // Un client qui doit : la fiche montre alors sa dette.
      const api = await managerApi(request, DEMO);
      const debts = await api.get("/debts?party_type=customer&status=open&page_size=1");
      await page.goto(`/customers/${debts.items[0].customer_id as string}`);
    },
  },
  { name: "fournisseurs", open: (page) => page.goto("/suppliers").then(() => undefined) },
  {
    name: "personne-nouvelle",
    open: (page) => page.goto("/customers/new").then(() => undefined),
  },
  {
    name: "fiche-fournisseur",
    open: async (page, request) => {
      await page.goto(`/suppliers/${await firstId(request, "/suppliers")}`);
    },
  },
  { name: "finance", open: (page) => page.goto("/finance").then(() => undefined) },
  {
    name: "encaisser-dette",
    open: (page) => page.goto("/finance/collect").then(() => undefined),
  },
  { name: "payer-fournisseur", open: (page) => page.goto("/finance/pay").then(() => undefined) },
  { name: "depenses", open: (page) => page.goto("/finance/expenses").then(() => undefined) },
  { name: "entrees-sorties", open: (page) => page.goto("/finance/cash").then(() => undefined) },
  { name: "dettes", open: (page) => page.goto("/finance/debts").then(() => undefined) },
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
