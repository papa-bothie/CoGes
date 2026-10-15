import { expect, test } from "@playwright/test";

import { DEMO, loginThroughUi } from "./fixtures";
import { SCREENS, settle } from "./screens";

/**
 * Réagencement (WCAG 1.4.10, audit de fin de phase 15) : à 320 px de large, soit un écran de
 * 1280 px zoomé à 400 %, aucune page ne défile horizontalement. Un tableau peut défiler dans
 * sa carte ; la page, jamais.
 */
test("aucun écran ne défile horizontalement à 320 px", async ({ page, request }) => {
  test.setTimeout(300_000);
  await page.goto("/login");
  await loginThroughUi(page, DEMO);
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
  await page.setViewportSize({ width: 320, height: 640 });

  const overflowing: string[] = [];
  for (const screen of SCREENS) {
    await screen.open(page, request);
    await settle(page);
    const widths = await page.evaluate(() => ({
      scroll: document.documentElement.scrollWidth,
      client: document.documentElement.clientWidth,
    }));
    if (widths.scroll > widths.client + 1) {
      overflowing.push(`${screen.name} (${widths.scroll} px pour ${widths.client})`);
    }
    await page.keyboard.press("Escape");
  }
  expect(overflowing, "écrans qui débordent à 320 px").toEqual([]);
});
