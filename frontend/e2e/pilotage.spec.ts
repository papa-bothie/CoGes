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
  await page.goto("/finance?tab=debts&party=customer&status=open&page_size=100");
  const row = page.getByRole("row", { name: new RegExp(customer.name) }).first();
  await row.getByRole("button", { name: "Régler" }).click();

  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText(`Règlement — ${customer.name}`)).toBeVisible();
  await dialog.getByLabel("Montant versé").fill("5000");
  await dialog.getByRole("button", { name: "Répartir" }).click();
  await dialog.getByRole("button", { name: "Enregistrer le règlement" }).click();
  await expect(page.getByText("Règlement enregistré.")).toBeVisible();

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
  await expect(page.getByRole("row", { name: new RegExp(customer.name) })).toHaveCount(0);
});

// Classement et recommandations : il faut l'historique de la démo, que ces deux
// parcours lisent sans y créer d'article.
test("changer de métrique change le classement et son libellé", async ({ page }) => {
  await login(page, DEMO);
  await page.goto("/analytics");
  await expect(page.getByTestId("ranking-title")).toContainText("chiffre d'affaires généré", {
    timeout: 30_000,
  });

  await page.getByRole("combobox", { name: "Métrique" }).click();
  await page.getByRole("option", { name: "Quantité vendue" }).click();

  await expect(page).toHaveURL(/metric=quantity/);
  await expect(page.getByTestId("ranking-title")).toHaveText("Classement par quantité vendue");
  await expect(page.getByTestId("metric-definition")).toContainText("Unités écoulées");
  const rows = page.locator("tbody tr");
  const count = await rows.count();
  expect(count).toBeGreaterThan(0);
  // La métrique est nommée sur **chaque** ligne, jamais un classement anonyme.
  for (let index = 0; index < count; index += 1) {
    await expect(rows.nth(index).getByRole("cell").nth(2)).toHaveText("Quantité vendue");
  }
  await expect(page.getByText(/meilleur/i)).toHaveCount(0);
});

test("une recommandation écartée quitte la liste des nouvelles", async ({ page, request }) => {
  const client = await managerApi(request, DEMO);
  const fresh = await client.get("/insights?status=new&page_size=100");
  test.skip(fresh.items.length === 0, "Aucune recommandation nouvelle dans le jeu de démo.");
  const insight = fresh.items[0] as { id: string; title: string };

  await login(page, DEMO);
  await page.goto("/insights");
  const card = page.getByRole("button", { name: new RegExp(insight.title) }).first();
  await card.click();
  const panel = page.getByRole("dialog");
  await expect(panel.getByText(insight.title).first()).toBeVisible();
  // Le panneau date et qualifie toujours la recommandation.
  await expect(panel.getByText("Date de calcul", { exact: true }).first()).toBeVisible();
  await expect(panel.getByText("Modèle", { exact: true }).first()).toBeVisible();
  await panel.getByRole("button", { name: "Écarter" }).click();
  await expect(page.getByText("Recommandation : écarté.")).toBeVisible();

  const after = await client.get("/insights?status=dismissed&page_size=100");
  expect(after.items.map((item: { id: string }) => item.id)).toContain(insight.id);
  const stillNew = await client.get("/insights?status=new&page_size=100");
  expect(stillNew.items.map((item: { id: string }) => item.id)).not.toContain(insight.id);
});

test("un vendeur n'accède pas aux paramètres, ni à l'écran ni à l'API", async ({
  page,
  request,
}) => {
  const seller = await createSalesperson(request);
  await login(page, seller);

  // Côté front : aucune entrée de menu, aucun onglet.
  await expect(page.getByRole("link", { name: "Paramètres" })).toHaveCount(0);
  await page.goto("/settings");
  await expect(page.getByRole("heading", { level: 1, name: "Paramètres" })).toBeVisible();
  await expect(page.getByRole("tab")).toHaveCount(0);

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
  ] as const) {
    const response = await request[method](path, {
      headers,
      data: method === "patch" ? { name: "Piratée" } : undefined,
    });
    expect(response.status(), `${method.toUpperCase()} ${path}`).toBe(403);
  }
});
