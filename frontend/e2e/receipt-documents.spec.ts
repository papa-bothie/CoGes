import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { E2E, loginThroughUi, managerApi, managerToken, stockedProduct } from "./fixtures";

/**
 * Ticket et facture refaits (prompt 35, bloc F, ADR 0112) : le logo et l'adresse en tête,
 * la description sous la désignation de la facture, axe en clair et en sombre, 360 px.
 * Bloc T (ADR 0113) : « Télécharger le PDF » et « Partager » (Web Share simulé).
 */
test.describe.configure({ timeout: 120_000, mode: "serial" });

const LOGO = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAIAAAABCAIAAAB7QOjdAAAAD0lEQVR4nGM8wcDAwMAAAAS+AMq34uUzAAAAAElFTkSuQmCC",
  "base64",
);

async function logo(request: APIRequestContext, put: boolean) {
  const headers = { Authorization: `Bearer ${await managerToken(request, E2E)}` };
  if (put) {
    const response = await request.put("/api/v1/companies/me/logo", {
      headers,
      multipart: { file: { name: "logo.png", mimeType: "image/png", buffer: LOGO } },
    });
    expect(response.status()).toBe(200);
  } else {
    await request.delete("/api/v1/companies/me/logo", { headers });
  }
}

async function noViolation(page: Page) {
  await page.mouse.move(0, 0);
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();
    expect(results.violations, scheme).toEqual([]);
  }
  await page.emulateMedia({ colorScheme: "light" });
}

let saleId = "";
let returnId = "";
let shop = "";
let address = "";

test.beforeAll(async ({ request }) => {
  const client = await managerApi(request);
  const company = await client.get("/companies/me");
  shop = company.name;
  address = company.address ?? "";
  if (!address) {
    address = "Rue 10, Médina, Dakar";
    await client.patch("/companies/me", { address });
  }
  const product = await stockedProduct(client, {
    stock: "10",
    price: "1500",
    description: "Sac cousu, 25 kg",
  });
  const sale = await client.post("/sales", {});
  await client.post(`/sales/${sale.id}/items`, { product_id: product.id, qty: "2" });
  await client.post(`/sales/${sale.id}/confirm`, { paid_amount: "3000", method: "cash" });
  saleId = sale.id;
  const detail = await client.get(`/sales/${sale.id}`);
  const created = await client.post(`/sales/${sale.id}/returns`, {
    lines: [{ sale_item_id: detail.items[0].id, qty: "1" }],
    reason: "Abîmé",
  });
  returnId = created.id;
  await logo(request, true);
});

test.afterAll(async ({ request }) => logo(request, false));

async function open(page: Page, format: "ticket" | "a4") {
  await page.goto("/login");
  await loginThroughUi(page, E2E);
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
  await page.goto(`/sales/${saleId}/receipt?format=${format}`);
}

test("le ticket porte le logo en noir et blanc et l'adresse", async ({ page }) => {
  await open(page, "ticket");
  const image = page.getByRole("img", { name: `Logo de ${shop}` });
  await expect(image).toHaveAttribute("src", /^data:image\/png;base64,/);
  await expect(image).toHaveClass(/grayscale/);
  await expect(page.getByRole("article").getByText(address)).toBeVisible();
  await noViolation(page);
});

test("la facture A4 : logo, adresse, description sous la désignation", async ({ page }) => {
  await open(page, "a4");
  await expect(page.getByRole("img", { name: `Logo de ${shop}` })).toBeVisible();
  const invoice = page.getByRole("article");
  await expect(invoice.getByText("FACTURE", { exact: true })).toBeVisible();
  await expect(invoice.getByText(address).first()).toBeVisible();
  await expect(invoice.getByText("Sac cousu, 25 kg")).toBeVisible();
  await noViolation(page);
});

test("à 360 px, la page du reçu ne défile pas en largeur", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 780 });
  await open(page, "ticket");
  await expect(page.getByRole("img", { name: `Logo de ${shop}` })).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
});

async function downloaded(page: Page, button: string): Promise<{ name: string; head: string }> {
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: button }).click(),
  ]);
  const stream = await download.createReadStream();
  const chunks: Buffer[] = [];
  for await (const chunk of stream) chunks.push(Buffer.from(chunk));
  return {
    name: download.suggestedFilename(),
    head: Buffer.concat(chunks).subarray(0, 5).toString(),
  };
}

test("« Télécharger le PDF » donne la facture nommée, en PDF", async ({ page }) => {
  await open(page, "a4");
  const file = await downloaded(page, "Télécharger le PDF");
  expect(file.name).toMatch(/^Facture-\d{4,}-[A-Za-z0-9-]+\.pdf$/);
  expect(file.head).toBe("%PDF-");
});

test("« Partager » passe le PDF du ticket au partage du téléphone", async ({ page }) => {
  await page.addInitScript(() => {
    const shared: { name: string; type: string; size: number }[] = [];
    Object.assign(window, { __shared: shared });
    Object.defineProperty(navigator, "canShare", { value: () => true });
    Object.defineProperty(navigator, "share", {
      value: async (data: ShareData) => {
        for (const file of data.files ?? []) {
          shared.push({ name: file.name, type: file.type, size: file.size });
        }
      },
    });
  });
  await open(page, "ticket");
  await page.getByRole("button", { name: "Partager" }).click();
  await expect
    .poll(() => page.evaluate(() => (window as unknown as { __shared: unknown[] }).__shared.length))
    .toBe(1);
  const [file] = await page.evaluate(
    () =>
      (window as unknown as { __shared: { name: string; type: string; size: number }[] }).__shared,
  );
  expect(file!.name).toMatch(/^Ticket-\d{4,}-.+\.pdf$/);
  expect(file!.type).toBe("application/pdf");
  expect(file!.size).toBeGreaterThan(1000);
});

test("le bon de retour se télécharge en PDF", async ({ page }) => {
  await page.goto("/login");
  await loginThroughUi(page, E2E);
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
  await page.goto(`/sales/returns/${returnId}/receipt`);
  await expect(page.getByRole("img", { name: `Logo de ${shop}` })).toBeVisible();
  const file = await downloaded(page, "Télécharger le PDF");
  expect(file.name).toMatch(/^Retour-\d{4,}-.+\.pdf$/);
  expect(file.head).toBe("%PDF-");
  await noViolation(page);
});
