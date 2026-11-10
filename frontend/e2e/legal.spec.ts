import { execFileSync } from "node:child_process";

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { E2E, LEGAL_HEADING, loginThroughUi, managerApi, type Credentials } from "./fixtures";

/**
 * Pages légales (prompt 36, ADR 0117) : `/conditions` et `/confidentialite` s'ouvrent sans
 * connexion et sans un appel à l'API ; `/cgu` et `/cgv` y mènent ; un compte accepte une fois
 * les textes au premier login, plus ensuite, et de nouveau quand la version change.
 */
test.describe.configure({ timeout: 90_000 });

const AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

async function axe(page: Page) {
  const result = await new AxeBuilder({ page }).withTags(AXE_TAGS).analyze();
  expect(result.violations).toEqual([]);
}

test.describe("textes publics", () => {
  for (const [path, title] of [
    ["/conditions", "Conditions générales d'utilisation et de vente"],
    ["/confidentialite", "Politique de confidentialité"],
  ] as const) {
    test(`${path} s'ouvre en navigation privée, sans appel à l'API`, async ({ browser }) => {
      // Contexte neuf : aucun cookie, aucun stockage, aucun worker (navigation privée).
      const context = await browser.newContext();
      const page = await context.newPage();
      const apiCalls: string[] = [];
      page.on("request", (request) => {
        if (new URL(request.url()).pathname.startsWith("/api/")) apiCalls.push(request.url());
      });
      const response = await page.goto(path);
      expect(response?.status()).toBe(200);
      await expect(page).toHaveURL(new RegExp(`${path}$`));
      await expect(page.getByRole("heading", { level: 1, name: title })).toBeVisible();
      await expect(page.getByText(/^Version du \d{2}\/\d{2}\/\d{4}$/)).toBeVisible();
      await expect(page.getByRole("table").first()).toBeVisible();
      await expect(page.locator('meta[name="robots"]')).toHaveAttribute("content", "index, follow");
      await page.waitForLoadState("networkidle");
      expect(apiCalls).toEqual([]);
      await context.close();
    });
  }

  test("/cgu et /cgv mènent pour de bon à /conditions", async ({ request }) => {
    for (const path of ["/cgu", "/cgv"]) {
      const response = await request.get(path, { maxRedirects: 0 });
      expect(response.status()).toBe(308);
      expect(response.headers()["location"]).toBe("/conditions");
    }
  });

  test("lisible sur téléphone, en clair et en sombre : aucun défilement de la page", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 360, height: 780 });
    for (const scheme of ["light", "dark"] as const) {
      await page.emulateMedia({ colorScheme: scheme });
      for (const path of ["/conditions", "/confidentialite"]) {
        await page.goto(path);
        const overflow = await page.evaluate(
          () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
        );
        expect(overflow, `${path} (${scheme})`).toBeLessThanOrEqual(0);
        // Le tableau défile dans son cadre, accessible au clavier.
        await expect(page.getByRole("region").first()).toHaveAttribute("tabindex", "0");
        await axe(page);
      }
    }
  });

  test("les liens sont au pied de la connexion et de la vitrine", async ({ page }) => {
    await page.goto("/login");
    const legal = page.getByRole("navigation", { name: "Textes légaux" });
    await expect(
      legal.getByRole("link", { name: "Conditions d'utilisation et de vente" }),
    ).toHaveAttribute("href", "/conditions");
    await expect(legal.getByRole("link", { name: "Confidentialité" })).toHaveAttribute(
      "href",
      "/confidentialite",
    );
    await page.goto("/");
    await page
      .getByRole("navigation", { name: "Textes légaux" })
      .getByRole("link", { name: "Confidentialité" })
      .click();
    await expect(
      page.getByRole("heading", { level: 1, name: "Politique de confidentialité" }),
    ).toBeVisible();
  });
});

test.describe("acceptation", () => {
  test.describe.configure({ mode: "serial" });
  const created: string[] = [];
  let seller: Credentials;

  test.beforeAll(async ({ request }) => {
    const client = await managerApi(request);
    const roles = await client.get("/roles?page_size=50");
    const role = roles.items.find((item: { name: string }) => item.name === "vendeur");
    const email = `legal-${Date.now()}@${E2E.slug}.example.com`;
    const password = `${E2E.slug}-vendeur-textes-2026`;
    const user = await client.post("/users", {
      email,
      full_name: "Vendeur des textes",
      password,
      role_ids: [role.id],
    });
    created.push(user.id as string);
    seller = { slug: E2E.slug, email, password };
  });

  test.afterAll(async ({ request }) => {
    const client = await managerApi(request);
    for (const id of created) await client.patch(`/users/${id}`, { is_active: false });
  });

  async function signIn(page: Page) {
    await page.goto("/login");
    await loginThroughUi(page, seller, { acceptLegal: false });
  }

  test("premier login : « Avant de continuer », puis l'application", async ({ page }) => {
    await signIn(page);
    await expect(page).toHaveURL(/\/acceptation$/, { timeout: 30_000 });
    await expect(page.getByRole("heading", { level: 1, name: LEGAL_HEADING })).toBeVisible();

    // Rien d'autre n'est accessible : une page de l'application y ramène.
    await page.goto("/sales");
    await expect(page).toHaveURL(/\/acceptation$/, { timeout: 30_000 });

    const button = page.getByRole("button", { name: "Accepter et continuer" });
    await expect(button).toBeDisabled();
    await axe(page);
    await page.emulateMedia({ colorScheme: "dark" });
    await axe(page);
    await page.emulateMedia({ colorScheme: "light" });

    await page.getByRole("checkbox", { name: /J'ai lu et j'accepte/ }).check();
    await expect(button).toBeEnabled();
    await button.click();
    await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
    await expect(page.getByRole("heading", { level: 1, name: /^Bonjour / })).toBeVisible();
  });

  test("second login : plus d'écran d'acceptation", async ({ page }) => {
    await signIn(page);
    await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
    await expect(page.getByRole("heading", { level: 1, name: /^Bonjour / })).toBeVisible();
    // Les deux liens restent dans le menu du compte.
    await page.getByRole("button", { name: "Réglages et compte" }).click();
    await expect(
      page.getByRole("menuitem", { name: "Conditions d'utilisation et de vente" }),
    ).toBeVisible();
    await expect(page.getByRole("menuitem", { name: "Confidentialité" })).toBeVisible();
  });

  test("nouvelle version : l'écran revient", async ({ page }) => {
    execFileSync("../deploy/scripts/e2e.sh", ["system", "legal-stale", seller.email], {
      stdio: "inherit",
    });
    await signIn(page);
    await expect(page).toHaveURL(/\/acceptation$/, { timeout: 30_000 });
    await page.getByRole("checkbox", { name: /J'ai lu et j'accepte/ }).check();
    await page.getByRole("button", { name: "Accepter et continuer" }).click();
    await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
  });

  test("à 360 px, l'écran tient sans défilement de côté", async ({ page }) => {
    execFileSync("../deploy/scripts/e2e.sh", ["system", "legal-stale", seller.email], {
      stdio: "inherit",
    });
    await page.setViewportSize({ width: 360, height: 780 });
    await signIn(page);
    await expect(page).toHaveURL(/\/acceptation$/, { timeout: 30_000 });
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });
});
