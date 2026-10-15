import { expect, test, type Page } from "@playwright/test";

import {
  createSalesperson,
  customerWithCredit,
  DEMO,
  E2E,
  loginThroughUi,
  managerApi,
  stockedProduct,
} from "./fixtures";

// Le serveur de développement compile chaque page à la première visite.
test.describe.configure({ timeout: 60_000 });

async function login(page: Page, credentials = E2E) {
  await page.goto("/login");
  await loginThroughUi(page, credentials);
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
}

test("un paiement réparti solde deux dettes du même client", async ({ page, request }) => {
  const client = await managerApi(request);
  const product = await stockedProduct(client, { stock: "10" });
  const customer = await customerWithCredit(client);
  // Deux ventes à crédit : 2 000 et 3 000 FCFA, donc deux dettes.
  for (const qty of ["2", "3"]) {
    const sale = await client.post("/sales", { customer_id: customer.id });
    await client.post(`/sales/${sale.id}/items`, { product_id: product.id, qty });
    await client.post(`/sales/${sale.id}/confirm`, { paid_amount: "0", method: "cash" });
  }
  const before = await client.get(`/debts?customer_id=${customer.id}`);
  expect(before.items).toHaveLength(2);

  await login(page);
  await page.goto("/finance/debts?party=customer&status=open&page_size=100");
  const row = page
    .getByRole("main")
    .getByRole("listitem")
    .filter({ hasText: customer.name })
    .first();
  await row.getByRole("button", { name: "Régler" }).click();

  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading", { name: "Encaisser une dette" })).toBeVisible();
  await expect(dialog.getByText(customer.name)).toBeVisible();
  // Montant au pavé numérique (tablette sans clavier) ; il couvre les dettes les plus
  // anciennes d'abord (lot 1).
  await dialog.getByRole("button", { name: "5", exact: true }).click();
  await dialog.getByRole("button", { name: "000", exact: true }).click();
  await expect(dialog.getByLabel("Combien il paie ?")).toHaveValue("5000");
  await expect(dialog.getByText("Il ne devra plus rien")).toBeVisible();
  await dialog.getByRole("button", { name: "Encaisser" }).click();
  await expect(page.getByText("Dette encaissée.")).toBeVisible();

  // Soldes relus sur le serveur : les deux dettes sont soldées par un seul versement.
  const after = await client.get(`/debts?customer_id=${customer.id}`);
  for (const debt of after.items) {
    expect(debt.status).toBe("paid");
    expect(debt.balance).toBe("0.00");
  }
  const paymentIds = new Set(
    after.items.flatMap((debt: { allocations: { payment_id: string }[] }) =>
      debt.allocations.map((allocation) => allocation.payment_id),
    ),
  );
  expect(paymentIds.size).toBe(1);

  // L'écran le reflète : plus aucune dette ouverte pour ce client.
  await expect(
    page.getByRole("main").getByRole("listitem").filter({ hasText: customer.name }),
  ).toHaveCount(0);
});

// Classement et recommandations : il faut l'historique de la démo, que ces deux
// parcours lisent sans y créer d'article.
test("changer de puce change le classement et le dit", async ({ page }) => {
  await login(page, DEMO);
  // Les analyses ont rejoint les Conseils (ADR 0074).
  await page.goto("/analytics");
  await expect(page).toHaveURL(/\/insights\?view=best$/);
  await expect(page.getByRole("heading", { name: /Ce qui vous rapporte le plus/ })).toBeVisible({
    timeout: 30_000,
  });

  await page.getByRole("button", { name: "Se vend le plus" }).click();
  await expect(page.getByRole("heading", { name: /Ce qui se vend le plus/ })).toBeVisible();
  const rows = page.getByRole("listitem").filter({ hasText: / vendus$/ });
  await expect(rows.first()).toBeVisible();
  // Chaque valeur dit son unité : jamais un classement anonyme.
  for (const text of await rows.allInnerTexts()) expect(text).toMatch(/ vendus$/);
});

test("un conseil marqué « C'est fait » est résolu, sa raison reste lisible", async ({
  page,
  request,
}) => {
  const client = await managerApi(request, DEMO);
  const live = await client.get("/insights?page_size=100");
  const actionable = (live.items as { id: string; title: string; insight_type: string }[]).filter(
    (item) => item.insight_type !== "insufficient_history",
  );
  test.skip(actionable.length === 0, "Aucun conseil dans le jeu de démo.");
  const insight = actionable[0]!;

  await login(page, DEMO);
  await page.goto("/insights");
  const card = page.getByRole("listitem").filter({ hasText: insight.title }).first();
  // « Pourquoi ? » date et qualifie toujours le conseil (métrique, modèle).
  await card.getByRole("button", { name: "Pourquoi ?" }).click();
  const panel = page.getByRole("dialog");
  await expect(panel.getByText("Date de calcul", { exact: true }).first()).toBeVisible();
  await expect(panel.getByText("Modèle", { exact: true }).first()).toBeVisible();
  await page.keyboard.press("Escape");

  await card.getByRole("button", { name: "C'est fait" }).click();
  await expect(card.getByText("Fait, merci.")).toBeVisible();
  const resolved = await client.get("/insights?status=resolved&page_size=100");
  expect(resolved.items.map((item: { id: string }) => item.id)).toContain(insight.id);
});

test("un vendeur n'accède pas aux paramètres, ni à l'écran ni à l'API", async ({
  page,
  request,
}) => {
  const seller = await createSalesperson(request);
  await login(page, seller);

  // Côté front : aucune rubrique des réglages (ADR 0075).
  await page.goto("/settings");
  await expect(page.getByRole("heading", { level: 1, name: "Réglages" })).toBeVisible();
  await expect(
    page.getByRole("navigation", { name: "Rubriques des réglages" }).getByRole("link"),
  ).toHaveCount(0);

  // Côté API : chaque route refuse, quelle que soit l'interface.
  const signIn = await request.post("/api/v1/auth/login", {
    data: { company_slug: seller.slug, email: seller.email, password: seller.password },
  });
  const headers = { Authorization: `Bearer ${(await signIn.json()).access_token}` };
  for (const [method, path] of [
    ["get", "/api/v1/companies/me"],
    ["patch", "/api/v1/companies/me"],
    ["get", "/api/v1/users"],
    ["get", "/api/v1/roles"],
    ["get", "/api/v1/audit-logs"],
    ["get", "/api/v1/roles/abilities"],
    ["get", "/api/v1/analytics/history"],
  ] as const) {
    const response = await request[method](path, {
      headers,
      data: method === "patch" ? { name: "Piratée" } : undefined,
    });
    expect(response.status(), `${method.toUpperCase()} ${path}`).toBe(403);
  }
});
