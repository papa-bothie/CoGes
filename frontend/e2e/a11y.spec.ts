import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";

import { DEMO, loginThroughUi } from "./fixtures";
import { SCREENS, settle } from "./screens";

/**
 * Accessibilité WCAG 2 AA (axe) sur les écrans de référence, en clair et en sombre.
 * Le rapport détaillé est écrit dans test-results/a11y-<thème>.json. Aucune violation
 * « serious » ou « critical » n'est tolérée si `A11Y_STRICT=1`.
 */
const STRICT = process.env.A11Y_STRICT === "1";

for (const scheme of ["light", "dark"] as const) {
  test.describe(`accessibilité (${scheme})`, () => {
    test.use({ colorScheme: scheme });

    test("écrans de référence", async ({ page, request }) => {
      test.setTimeout(240_000);
      const report: Record<string, { id: string; impact: string | null; nodes: number }[]> = {};

      await page.goto("/login");
      const pages = [{ name: "connexion", open: async () => undefined }, ...SCREENS];
      for (const [index, screen] of pages.entries()) {
        if (index === 1) {
          await loginThroughUi(page, DEMO);
          await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
        }
        await screen.open(page, request);
        if (index > 0) await settle(page);
        const results = await new AxeBuilder({ page })
          .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
          .analyze();
        report[screen.name] = results.violations.map((violation) => ({
          id: violation.id,
          impact: violation.impact ?? null,
          nodes: violation.nodes.length,
        }));
      }

      mkdirSync("test-results", { recursive: true });
      writeFileSync(`test-results/a11y-${scheme}.json`, JSON.stringify(report, null, 2));
      const blocking = Object.entries(report).flatMap(([name, violations]) =>
        violations
          .filter((violation) => violation.impact === "serious" || violation.impact === "critical")
          .map((violation) => `${name}: ${violation.id} (${violation.nodes})`),
      );
      if (STRICT) expect(blocking, blocking.join("\n")).toEqual([]);
    });
  });
}
