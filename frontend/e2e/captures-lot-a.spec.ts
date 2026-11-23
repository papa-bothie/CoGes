import { expect, test } from "@playwright/test";

import { E2E, loginThroughUi, managerApi, stockedProduct } from "./fixtures";

/**
 * Captures avant / après de la facture claire (prompt 40, lot A, R2) dans
 * docs/design/captures/lot-a/ : la facture à l'écran (1280 px) et telle que le navigateur
 * l'imprime (`media: print`). Ne tourne que si `CAPTURES_STAGE` est défini :
 *
 *   CAPTURES_STAGE=avant pnpm exec playwright test captures-lot-a
 */
const STAGE = process.env.CAPTURES_STAGE;

test("captures de la facture", async ({ page, request }) => {
  test.skip(!STAGE, "CAPTURES_STAGE non défini");
  test.setTimeout(120_000);
  const client = await managerApi(request);
  const product = await stockedProduct(client, {
    stock: "10",
    price: "1500",
    description: "Sac cousu, 25 kg",
  });
  const sale = await client.post("/sales", {});
  await client.post(`/sales/${sale.id}/items`, { product_id: product.id, qty: "2" });
  await client.post(`/sales/${sale.id}/confirm`, { paid_amount: "3000", method: "cash" });

  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/login");
  await loginThroughUi(page, E2E);
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
  await page.goto(`/sales/${sale.id}/receipt?format=a4`);
  const invoice = page.getByRole("article");
  await expect(invoice.getByText("FACTURE", { exact: true })).toBeVisible();
  await page.addStyleTag({ content: "nextjs-portal { display: none !important; }" });
  const dir = `../docs/design/captures/lot-a`;
  await invoice.screenshot({ path: `${dir}/${STAGE}-ecran.png`, animations: "disabled" });
  await page.emulateMedia({ media: "print" });
  await invoice.screenshot({ path: `${dir}/${STAGE}-impression.png`, animations: "disabled" });
});
