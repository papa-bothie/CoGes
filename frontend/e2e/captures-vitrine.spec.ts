import { readFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { DEMO, loginThroughUi } from "./fixtures";
import { settle } from "./screens";

/**
 * Captures de la page d'accueil publique (prompt 37, ADR 0115), sur la démo (`make e2e-reset`,
 * épicerie `demo`) : jamais de données réelles de commerçant. Ne tourne que si
 * `VITRINE_CAPTURES` nomme un dossier ; `scripts/vitrine-images.py` les convertit ensuite en
 * WebP dans `public/vitrine/`.
 *
 *   VITRINE_CAPTURES=/tmp/vitrine pnpm exec playwright test captures-vitrine
 */
const OUT = process.env.VITRINE_CAPTURES;

/**
 * Sans relais en e2e, l'accueil annonce « Certains chiffres se mettent à jour » : un état de la
 * pile de test, pas de l'application. Le bandeau est retiré de la capture, rien d'autre.
 */
async function hidePendingBanner(page: Page) {
  await page
    .getByText("Certains chiffres se mettent à jour", { exact: false })
    .evaluateAll((nodes) => nodes.forEach((node) => node.closest("[role=status], div")?.remove()));
}

test.describe("captures de la vitrine", () => {
  test.skip(!OUT, "VITRINE_CAPTURES non défini");
  test.use({ colorScheme: "light" });

  test("ordinateur : la caisse", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/login");
    await loginThroughUi(page, DEMO);
    await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
    await page.goto("/sales/new");
    await settle(page);
    await page.screenshot({ path: `${OUT}/ordinateur.png`, animations: "disabled" });
  });

  test("téléphone : l'accueil", async ({ browser }) => {
    const context = await browser.newContext({
      viewport: { width: 390, height: 844 },
      deviceScaleFactor: 2,
      isMobile: true,
      hasTouch: true,
      colorScheme: "light",
      locale: "fr-FR",
      timezoneId: "Africa/Dakar",
    });
    const page = await context.newPage();
    await page.goto("/login");
    await loginThroughUi(page, DEMO);
    await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
    await settle(page);
    await hidePendingBanner(page);
    await page.screenshot({ path: `${OUT}/telephone.png`, animations: "disabled" });
    await context.close();
  });

  test("image de partage (1200 × 630)", async ({ page }) => {
    const asset = (path: string, type: string) =>
      `data:${type};base64,${readFileSync(path).toString("base64")}`;
    const front = join(__dirname, "..");
    const font = asset(join(front, "app/fonts/figtree-latin.woff2"), "font/woff2");
    const logo = asset(join(front, "public/brand/coges-logo.png"), "image/png");
    // Capture de la caisse prise juste avant (même dossier).
    const screen = asset(`${OUT}/ordinateur.png`, "image/png");
    await page.setViewportSize({ width: 1200, height: 630 });
    // Couleurs de la maquette v2 (docs/design/DESIGN.md) : vert de marque sur teinte des ventes.
    await page.setContent(`<!doctype html><html><head><style>
      @font-face { font-family: Figtree; src: url(${font}) format("woff2"); font-weight: 300 900; }
      body { margin: 0; width: 1200px; height: 630px; overflow: hidden; background: #e6f4ec;
        font-family: Figtree, sans-serif; color: #024a2c; position: relative; }
      .texte { position: absolute; left: 72px; top: 72px; width: 520px; }
      .logo { width: 300px; }
      h1 { font-size: 60px; line-height: 1.08; font-weight: 800; margin: 48px 0 20px; }
      p { font-size: 28px; line-height: 1.35; margin: 0; color: #1e2320; }
      .ecran { position: absolute; left: 640px; top: 96px; width: 760px; border-radius: 22px;
        border: 10px solid #1e2320; box-shadow: 0 30px 60px rgba(2, 74, 44, 0.25); }
    </style></head><body>
      <div class="texte"><img class="logo" src="${logo}" alt="">
        <h1>Votre boutique, simplement.</h1>
        <p>Ventes, stock et argent de la boutique, sur téléphone et ordinateur.</p></div>
      <img class="ecran" src="${screen}" alt="">
    </body></html>`);
    await page.evaluate(() => document.fonts.ready);
    await page.screenshot({ path: `${OUT}/partage.png` });
  });
});
