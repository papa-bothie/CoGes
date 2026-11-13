import { expect, test, type Page } from "@playwright/test";

import { DEMO, loginThroughUi } from "./fixtures";

/**
 * Pages d'entrée toujours claires (prompt 39, bloc C, ADR 0123) : appareil en sombre **et**
 * « sombre » choisi dans l'application. L'application connectée garde le choix de la
 * personne, que la visite n'a ni effacé ni modifié.
 */
const PAGES = ["/", "/login", "/inscription", "/verification", "/conditions", "/confidentialite"];
const PAPIER = "rgb(251, 248, 243)";

test.use({ colorScheme: "dark" });

/** Toute classe posée sur <html> depuis le premier octet : un éclair sombre s'y verrait. */
async function recordHtmlClasses(page: Page) {
  await page.addInitScript(() => {
    const seen: string[] = [];
    (window as unknown as { __classes: string[] }).__classes = seen;
    const record = () => seen.push(document.documentElement.className);
    record();
    new MutationObserver(record).observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class"],
    });
  });
}

/** Contraste WCAG entre deux couleurs `rgb(…)` calculées. */
function contrast(a: string, b: string): number {
  const lum = (color: string) => {
    const [r = 0, g = 0, bl = 0] = color
      .match(/\d+(\.\d+)?/g)!
      .slice(0, 3)
      .map(Number)
      .map((v) => {
        const c = v / 255;
        return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
      });
    return 0.2126 * r + 0.7152 * g + 0.0722 * bl;
  };
  const [x, y] = [lum(a), lum(b)];
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
}

test("appareil et choix en sombre : les pages d'entrée restent claires, l'application non", async ({
  page,
}) => {
  test.setTimeout(120_000);
  await recordHtmlClasses(page);
  // Le choix « sombre » de la personne, posé une seule fois.
  await page.goto("/conditions");
  await page.evaluate(() => localStorage.setItem("theme", "dark"));

  for (const path of PAGES) {
    await page.goto(path);
    const state = await page.evaluate(() => {
      const body = getComputedStyle(document.body);
      const meta = (name: string) =>
        document.querySelector(`meta[name="${name}"]`)?.getAttribute("content") ?? null;
      const field = document.querySelector("input:not([type=hidden]):not([type=checkbox])");
      return {
        classes: (window as unknown as { __classes: string[] }).__classes,
        background: body.backgroundColor,
        color: body.color,
        scheme: getComputedStyle(document.documentElement).colorScheme,
        metaScheme: meta("color-scheme"),
        themeColor: meta("theme-color"),
        field: field ? getComputedStyle(field).backgroundColor : null,
        stored: localStorage.getItem("theme"),
      };
    });
    expect(
      state.classes.some((value) => /\bdark\b/.test(value)),
      path,
    ).toBe(false);
    expect(state.background, path).toBe(PAPIER);
    expect(contrast(state.color, state.background), path).toBeGreaterThanOrEqual(4.5);
    expect(state.scheme, path).toBe("light");
    expect(state.metaScheme, path).toBe("light");
    expect(state.themeColor, path).toBe("#fbf8f3");
    if (state.field) expect(contrast(state.field, "rgb(0, 0, 0)"), path).toBeGreaterThan(10);
    expect(state.stored, path).toBe("dark");
  }

  // Connecté : le sombre de la personne revient, sans rechargement de la page.
  await page.goto("/login");
  await loginThroughUi(page, DEMO);
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
  await expect(page.locator("html")).toHaveClass(/\bdark\b/);
  const app = await page.evaluate(() => ({
    background: getComputedStyle(document.body).backgroundColor,
    stored: localStorage.getItem("theme"),
    themeColor: document.querySelector('meta[name="theme-color"]'),
  }));
  expect(app.background).not.toBe(PAPIER);
  expect(app.stored).toBe("dark");
  // Rechargée, l'application reste sombre ; la barre du navigateur n'y est pas forcée.
  await page.reload();
  await expect(page.locator("html")).toHaveClass(/\bdark\b/);
  expect(await page.locator('meta[name="theme-color"]').count()).toBe(0);

  // Les conditions ouvertes depuis le menu du compte (navigation sans rechargement) : claires,
  // puis le retour à l'application rend le sombre.
  await page.getByRole("button", { name: "Réglages et compte" }).click();
  await page.getByRole("menuitem", { name: "Conditions d'utilisation et de vente" }).click();
  await expect(page).toHaveURL(/\/conditions$/);
  await expect(page.locator("html")).not.toHaveClass(/\bdark\b/);
  expect(await page.evaluate(() => getComputedStyle(document.body).backgroundColor)).toBe(PAPIER);
  await page.goBack();
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.locator("html")).toHaveClass(/\bdark\b/);
  expect(await page.evaluate(() => localStorage.getItem("theme"))).toBe("dark");
});

test("appareil en sombre, aucun choix enregistré : claires aussi, et rien n'est écrit", async ({
  page,
}) => {
  for (const path of PAGES) {
    await page.goto(path);
    await expect(page.locator("html")).not.toHaveClass(/\bdark\b/);
    expect(await page.evaluate(() => localStorage.getItem("theme"))).toBeNull();
  }
});
