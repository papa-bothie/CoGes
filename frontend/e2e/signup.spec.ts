import { execFileSync } from "node:child_process";

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { loginThroughUi, managerApi, stockedProduct, type Credentials } from "./fixtures";

/**
 * Inscription libre-service (lot 30, ADR 0118), sur l'API des parcours (inscription
 * ouverte, sans SMTP ni worker).
 *
 * Chemin e-mail : la vraie demande part ; seule la réponse est forcée à `path: "email"`
 * (sans SMTP, le serveur choisirait l'équipe — ce choix est prouvé par `test_signup.py`).
 * Le lien est celui qu'aurait envoyé le worker (`e2e.sh system signup-link`). Le reste est
 * réel : lien, activation, connexion, tableau de bord vide, première vente.
 */
test.describe.configure({ timeout: 120_000, mode: "serial" });

const AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];
const PASSWORD = ["ma", "boutique", "neuve", "2026"].join("-");

async function axe(page: Page) {
  const result = await new AxeBuilder({ page }).withTags(AXE_TAGS).analyze();
  expect(result.violations).toEqual([]);
}

function unique() {
  const marker = `${Date.now()}`.slice(-7);
  return { marker, phone: `77 ${marker.slice(0, 3)} ${marker.slice(3, 5)} ${marker.slice(5)}` };
}

async function fillForm(page: Page, values: { shop: string; phone: string; email?: string }) {
  await page.getByLabel("Nom de la boutique").fill(values.shop);
  await page.getByLabel("Votre nom").fill("Awa Ndiaye");
  await page.getByLabel("Numéro de téléphone").fill(values.phone);
  if (values.email) await page.getByLabel(/^E-mail/).fill(values.email);
  await page.getByLabel("Mot de passe", { exact: true }).fill(PASSWORD);
  await page.getByLabel("Retapez le mot de passe").fill(PASSWORD);
}

function signupLink(email: string): string {
  const out = execFileSync("../deploy/scripts/e2e.sh", ["system", "signup-link", email], {
    encoding: "utf8",
  });
  const line = out.split("\n").find((value) => value.includes("/verification/"));
  if (!line) throw new Error(`lien introuvable : ${out}`);
  return new URL(line.trim()).pathname;
}

test("le bouton « Créer ma boutique » mène au formulaire, depuis la vitrine et la connexion", async ({
  browser,
}) => {
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto("/");
  await page.getByRole("main").getByRole("link", { name: "Créer ma boutique" }).click();
  await expect(page).toHaveURL(/\/inscription$/);
  await expect(page.getByRole("heading", { level: 1, name: "Créer ma boutique" })).toBeVisible();
  await page.goto("/login");
  await expect(page.getByRole("link", { name: "Créer ma boutique" })).toHaveAttribute(
    "href",
    "/inscription",
  );
  await context.close();
});

test("chemin e-mail : lien, boutique prête, connexion, tableau de bord vide, première vente", async ({
  page,
  request,
}) => {
  const { marker, phone } = unique();
  const email = `awa-${marker}@example.com`;
  const shop = `Épicerie Parcours ${marker}`;
  // La vraie demande, par l'API ; la page reçoit la réponse du chemin e-mail.
  const created = await request.post("/api/v1/auth/signup-requests", {
    data: {
      shop_name: shop,
      full_name: "Awa Ndiaye",
      phone: `+221 ${phone}`,
      email,
      password: PASSWORD,
      accept_legal: true,
    },
  });
  expect(created.status()).toBe(202);
  await page.route("**/api/v1/auth/signup-requests", (route) =>
    route.fulfill({ status: 202, json: { path: "email", message: "Vérifiez votre boîte." } }),
  );

  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/inscription");
  // Rien dans l'adresse, et la case d'abord.
  const submit = page.getByRole("button", { name: "Créer ma boutique" });
  await expect(submit).toBeDisabled();
  await axe(page);
  await fillForm(page, { shop, phone, email });
  await page.getByRole("checkbox", { name: /J'ai lu et j'accepte/ }).check();
  await submit.click();

  const check = page.getByRole("heading", { name: "Vérifiez votre e-mail" });
  await expect(check).toBeFocused();
  await expect(page.getByText(/a•+@example\.com/)).toBeVisible();
  await expect(page).toHaveURL(/\/inscription$/);
  await axe(page);

  await page.goto(signupLink(email));
  await expect(page.getByRole("heading", { name: "Votre boutique est prête" })).toBeFocused({
    timeout: 30_000,
  });
  // Le jeton ne reste pas dans l'adresse.
  await expect(page).toHaveURL(/\/verification$/);
  const slug = (await page.locator("p.font-mono").textContent())?.trim() ?? "";
  expect(slug).toMatch(/^epicerie-parcours-/);
  await axe(page);

  await page.getByRole("link", { name: "Me connecter" }).click();
  await expect(page).toHaveURL(new RegExp(`/login\\?boutique=${slug}$`));
  await expect(page.getByLabel("Code de la boutique")).toHaveValue(slug);

  const credentials: Credentials = { slug, email, password: PASSWORD };
  await loginThroughUi(page, credentials);
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
  const firstSteps = page.getByRole("region", { name: "Pour bien démarrer" });
  await expect(firstSteps).toBeVisible();
  await expect(firstSteps.getByRole("link")).toHaveCount(3);

  // Première vente : un article (préparé par l'API, au nom du nouveau gérant), puis la caisse.
  const client = await managerApi(request, credentials);
  const product = await stockedProduct(client, { stock: "5", price: "1500" });
  await page.goto("/sales/new");
  await page.getByRole("searchbox", { name: "Chercher un article" }).fill(product.name);
  await page.getByRole("button", { name: `Ajouter ${product.name}` }).click();
  await page.getByRole("button", { name: /^Encaisser 1\s500\sF$/ }).click();
  await expect(page.getByRole("heading", { name: "Vente enregistrée" })).toBeVisible();
  await page.goto("/dashboard");
  await expect(page.getByRole("region", { name: "Pour bien démarrer" })).toHaveCount(0);
});

/** Mise en page partagée avec la connexion (prompt 39, bloc S, ADR 0123). */
async function expectEntreeLayout(page: Page, width: number) {
  const panel = page.locator("[data-entree-panneau]");
  const column = page.locator("[data-entree-colonne]");
  await expect(panel.getByText("Votre boutique, simplement.")).toBeVisible();
  const box = (await column.boundingBox())!;
  expect(box.width).toBeLessThanOrEqual(440);
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
  const panelBox = (await panel.boundingBox())!;
  if (width >= 768) {
    // Panneau vert à gauche, colonne à droite.
    expect(panelBox.x + panelBox.width).toBeLessThanOrEqual(box.x);
  } else {
    // Sur téléphone, le panneau est au-dessus et le titre reste dans le premier écran.
    expect(panelBox.y + panelBox.height).toBeLessThanOrEqual(box.y);
    const title = (await page.getByRole("heading", { level: 1 }).boundingBox())!;
    expect(title.y + title.height).toBeLessThan(page.viewportSize()!.height);
  }
}

for (const width of [1280, 360] as const) {
  test(`mise en page de la connexion à ${width} px : panneau, colonne de 440 px, lien vers la connexion`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: width === 360 ? 740 : 800 });
    await page.goto("/inscription");
    await expectEntreeLayout(page, width);
    if (width === 360) {
      await expect(page.getByLabel("Nom de la boutique")).toBeInViewport();
    }
    const already = page
      .locator("[data-entree-colonne]")
      .getByRole("link", { name: "Se connecter" });
    await expect(already).toHaveAttribute("href", "/login");
    await expect(page.getByText("J'ai déjà un compte")).toBeVisible();
    // Champ piège : hors écran et hors du parcours clavier, inchangé.
    const trap = page.getByLabel("Site web");
    await expect(trap).toHaveAttribute("tabindex", "-1");
    expect((await trap.boundingBox())?.x ?? -1).toBeLessThan(0);
    // Clavier seul : le premier arrêt du formulaire est le nom de la boutique.
    await page.getByRole("heading", { level: 1 }).focus();
    await page.keyboard.press("Tab");
    await expect(page.getByLabel("Nom de la boutique")).toBeFocused();
    await axe(page);

    await page.goto("/verification");
    await expect(
      page.getByRole("heading", { level: 1, name: "Ce lien ne marche plus" }),
    ).toBeFocused();
    await expectEntreeLayout(page, width);
    await axe(page);
  });
}

// L'activation par l'équipe, puis la connexion par le numéro : `frontend-admin/e2e`.
test("chemin sans e-mail : demande reçue, et la connexion dit qu'elle attend l'équipe", async ({
  page,
}) => {
  const { marker, phone } = unique();
  const shop = `Quincaillerie ${marker}`;
  await page.setViewportSize({ width: 360, height: 800 });
  await page.goto("/inscription");
  await fillForm(page, { shop, phone });
  await page.getByRole("checkbox", { name: /J'ai lu et j'accepte/ }).check();
  await page.getByRole("button", { name: "Créer ma boutique" }).click();

  await expect(page.getByRole("heading", { name: "Demande reçue" })).toBeFocused();
  await expect(page.getByRole("link", { name: /Nous écrire sur WhatsApp/ })).toHaveAttribute(
    "href",
    /^https:\/\/wa\.me\/\d+$/,
  );
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
  await axe(page);
  await page.emulateMedia({ colorScheme: "dark" });
  await axe(page);
  await page.emulateMedia({ colorScheme: "light" });

  // Avant l'activation, la connexion le dit, après le bon mot de passe seulement.
  await page.goto("/login");
  await loginThroughUi(page, { slug: "une-boutique", email: phone, password: PASSWORD });
  await expect(page.locator("form").getByRole("alert")).toContainText("en cours d'activation");
});

test("un lien qui ne marche plus : un seul message et un nouveau lien possible", async ({
  page,
}) => {
  await page.goto(`/verification/${"x".repeat(43)}`);
  await expect(page.getByRole("heading", { name: "Ce lien ne marche plus" })).toBeVisible({
    timeout: 30_000,
  });
  await expect(page).toHaveURL(/\/verification$/);
  await expect(page.getByRole("button", { name: "Recevoir un nouveau lien" })).toBeEnabled();
  await axe(page);
});
