import AxeBuilder from "@axe-core/playwright";
import { expect, test, type BrowserContext, type Page } from "@playwright/test";

import { DEMO, loginThroughUi } from "./fixtures";

/**
 * Page d'accueil publique (prompt 37, ADR 0115) : montrée au seul visiteur nouveau, sans
 * aucun changement pour qui se connecte déjà.
 */
const HOST = new URL(process.env.E2E_BASE_URL ?? "http://localhost:3100");

async function addMarker(context: BrowserContext, name: string) {
  await context.addCookies([{ name, value: "1", domain: HOST.hostname, path: "/" }]);
}

/** Toutes les requêtes de la page, pour vérifier qu'aucune ne part vers l'API ni ailleurs. */
function watchRequests(page: Page): string[] {
  const seen: string[] = [];
  page.on("request", (request) => seen.push(request.url()));
  return seen;
}

async function scrollThrough(page: Page) {
  // Charge les images différées (sous le pli).
  const height = await page.evaluate(() => document.body.scrollHeight);
  for (let y = 0; y <= height; y += 500) {
    await page.evaluate((top) => window.scrollTo(0, top), y);
    await page.waitForTimeout(50);
  }
  // Attente explicite des images différées, et non `networkidle` : avec les animations du
  // prompt 38, l'état « réseau calme » ne venait parfois jamais (2 fois sur 12), alors
  // qu'aucune requête de la page n'était en attente.
  // Seules les images affichées : une image masquée (`hidden lg:block`) ne se charge jamais.
  await page.waitForFunction(() =>
    [...document.images]
      .filter((image) => image.getClientRects().length > 0)
      .every((image) => image.complete),
  );
  // Apparitions et titre (prompt 38) menés à leur état final : axe mesure le contraste réel.
  await page.evaluate(() => {
    for (const animation of document.getAnimations()) {
      if (animation.timeline === document.timeline) animation.finish();
    }
  });
}

test.describe("vitrine : visiteur nouveau", () => {
  test("voit la vitrine, sans appel à l'API ni ressource externe", async ({ page }) => {
    const requests = watchRequests(page);
    const response = await page.goto("/");
    expect(page.url()).toBe(new URL("/", HOST).href);
    await expect(page.getByRole("heading", { level: 1 })).toContainText("au même endroit");
    await scrollThrough(page);

    expect(requests.filter((url) => new URL(url).pathname.startsWith("/api/"))).toEqual([]);
    expect(requests.filter((url) => new URL(url).origin !== HOST.origin)).toEqual([]);
    // Aucun formulaire : la page ne collecte rien.
    await expect(page.locator("form, input, textarea")).toHaveCount(0);
    // La CSP n'est pas assouplie (next.config.ts) : même origine, aucune exception tierce.
    const csp = response?.headers()["content-security-policy"] ?? "";
    expect(csp).toContain("default-src 'self'");
    expect(csp).toMatch(/connect-src 'self'(;| ws:;)/);
    expect(csp).toContain("img-src 'self' data: blob:");
    expect(csp).toContain("font-src 'self'");
    expect(csp).not.toMatch(/https?:/);
    // Aucun cookie posé pour un visiteur.
    expect(await page.context().cookies()).toEqual([]);
  });

  test("« Se connecter » est visible dès le premier écran et mène à la connexion", async ({
    page,
  }) => {
    await page.goto("/");
    const login = page.getByRole("banner").getByRole("link", { name: "Se connecter" });
    await expect(login).toBeInViewport();
    await login.click();
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByLabel("Code de la boutique")).toBeVisible();
  });

  test("les liens WhatsApp ouvrent wa.me avec le message prérempli", async ({ page }) => {
    await page.goto("/");
    const link = page.getByRole("link", { name: /Écrire sur WhatsApp/ }).first();
    const href = await link.getAttribute("href");
    expect(href).toMatch(/^https:\/\/wa\.me\/\d+\?text=/);
    await expect(link).toHaveAttribute("rel", /noopener/);
  });

  test("les routes de l'application renvoient toujours à la connexion", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/login$/);
    await page.goto("/sales/new");
    await expect(page).toHaveURL(/\/login\?next=%2Fsales%2Fnew$/);
  });

  test("robots.txt, sitemap.xml et l'image de partage répondent sans connexion", async ({
    request,
  }) => {
    const robots = await request.get("/robots.txt", { maxRedirects: 0 });
    expect(robots.status()).toBe(200);
    expect(await robots.text()).toMatch(/Disallow: \/\n/);
    const sitemap = await request.get("/sitemap.xml", { maxRedirects: 0 });
    expect(sitemap.status()).toBe(200);
    expect(await sitemap.text()).toContain("<loc>https://coges.app</loc>");
    const image = await request.get("/vitrine/partage.png", { maxRedirects: 0 });
    expect(image.status()).toBe(200);
    expect(image.headers()["content-type"]).toBe("image/png");
  });

  test("balises de partage et données structurées", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("html")).toHaveAttribute("lang", "fr");
    await expect(page.locator('meta[property="og:image"]')).toHaveAttribute(
      "content",
      "https://coges.app/vitrine/partage.png",
    );
    await expect(page.locator('meta[name="twitter:card"]')).toHaveAttribute(
      "content",
      "summary_large_image",
    );
    await expect(page.locator('meta[name="robots"]')).toHaveAttribute("content", "index, follow");
    const ld = JSON.parse(
      (await page.locator('script[type="application/ld+json"]').textContent()) ?? "[]",
    ) as { "@type": string; offers?: unknown }[];
    expect(ld.map((item) => item["@type"])).toEqual(["Organization", "SoftwareApplication"]);
    expect(ld.some((item) => item.offers)).toBe(false);
    // La connexion, elle, n'est pas indexable.
    await page.goto("/login");
    await expect(page.locator('meta[name="robots"]')).toHaveAttribute(
      "content",
      "noindex, nofollow",
    );
  });
});

test.describe("vitrine : commerçant de retour", () => {
  test("avec coges_known seul, / mène à la connexion", async ({ page, context }) => {
    await addMarker(context, "coges_known");
    await page.goto("/");
    await expect(page).toHaveURL(/\/login$/);
  });

  test("connecté, / mène à l'Accueil sans voir la vitrine, et le marqueur est posé", async ({
    page,
  }) => {
    await page.goto("/login");
    await loginThroughUi(page, DEMO);
    await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
    const known = (await page.context().cookies()).find((cookie) => cookie.name === "coges_known");
    expect(known?.value).toBe("1");
    expect(known?.httpOnly).toBe(false);
    expect(known?.sameSite).toBe("Lax");
    // Un an, à quelques secondes près.
    expect(known!.expires - Date.now() / 1000).toBeGreaterThan(364 * 24 * 3600);

    // Redirigé par le proxy avant tout rendu : la vitrine n'est jamais servie.
    const response = await page.goto("/");
    expect(response?.request().redirectedFrom()?.url()).toBe(new URL("/", HOST).href);
    await expect(page).toHaveURL(/\/dashboard$/);
    await expect(page.getByText("au même endroit")).toHaveCount(0);
  });

  test("un compte déjà connecté avant ce lot reçoit le marqueur à sa visite suivante", async ({
    page,
    context,
  }) => {
    await addMarker(context, "coges_session");
    await page.goto("/hors-ligne");
    const cookies = await context.cookies();
    expect(cookies.find((cookie) => cookie.name === "coges_known")?.value).toBe("1");
  });

  test("après la déconnexion, / mène à la connexion, pas à la vitrine", async ({ page }) => {
    await page.goto("/login");
    await loginThroughUi(page, DEMO);
    await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
    await page.context().clearCookies({ name: "coges_session" });
    await page.goto("/");
    await expect(page).toHaveURL(/\/login$/);
  });
});

test.describe("vitrine : accessibilité et téléphone", () => {
  for (const scheme of ["light", "dark"] as const) {
    test(`axe AA sans violation (${scheme === "light" ? "clair" : "sombre"})`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: scheme });
      await page.goto("/");
      await scrollThrough(page);
      // Les questions ouvertes aussi.
      for (const summary of await page.locator("summary").all()) await summary.click();
      const results = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
        .analyze();
      expect(
        results.violations.map((violation) => `${violation.id} (${violation.nodes.length})`),
      ).toEqual([]);
    });
  }

  test("360 px : aucun défilement horizontal, menu au clavier", async ({ page }) => {
    await page.setViewportSize({ width: 360, height: 740 });
    await page.goto("/");
    await scrollThrough(page);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth),
    ).toBeLessThanOrEqual(0);

    await page.evaluate(() => window.scrollTo(0, 0));
    await expect(
      page.getByRole("banner").getByRole("link", { name: "Se connecter" }),
    ).toBeInViewport();
    const menu = page.getByRole("button", { name: "Menu" });
    await menu.focus();
    await page.keyboard.press("Enter");
    await expect(menu).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByRole("navigation", { name: "Menu" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(menu).toHaveAttribute("aria-expanded", "false");
    await expect(menu).toBeFocused();
  });

  test("clavier seul : lien d'évitement, puis l'en-tête dans l'ordre", async ({ page }) => {
    await page.goto("/");
    await page.keyboard.press("Tab");
    await expect(page.getByRole("link", { name: "Aller au contenu" })).toBeFocused();
    const order: string[] = [];
    for (let index = 0; index < 6; index += 1) {
      await page.keyboard.press("Tab");
      order.push(
        await page.evaluate(() => (document.activeElement as HTMLElement | null)?.innerText ?? ""),
      );
    }
    expect(order.join("|")).toContain("Se connecter");
    // Une question se déplie au clavier.
    const question = page.locator("summary").first();
    await question.focus();
    await page.keyboard.press("Enter");
    await expect(page.locator("details").first()).toHaveAttribute("open", "");
  });
});
