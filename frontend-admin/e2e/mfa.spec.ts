import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import {
  API,
  apiToken,
  enrollOnScreen,
  freshCode,
  keepCodesAndEnter,
  signInAdmin,
  totp,
} from "./mfa";

/**
 * Double authentification obligatoire de l'administration (ADR 0105), de bout en bout :
 * enrôlement à l'acceptation d'une invitation (code calculé ici depuis la clé affichée),
 * connexion en deux temps, code de secours, régénération, réinitialisation par un autre
 * administrateur. axe AA en clair et en sombre, 360 px sans défilement horizontal.
 */
const PASSWORD = "demo-coges-2026";

async function axe(page: Page, where: string): Promise<void> {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  expect(results.violations, where).toEqual([]);
}

async function noHorizontalScroll(page: Page, where: string): Promise<void> {
  await expect
    .poll(
      () =>
        page.evaluate(
          () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
        ),
      { message: where, timeout: 10_000 },
    )
    .toBeLessThanOrEqual(0);
}

/** Un collègue invité par l'API ; le lien d'invitation, montré sans SMTP. */
async function invite(request: APIRequestContext): Promise<{ email: string; path: string }> {
  const suffix = crypto.randomUUID().slice(0, 6);
  const email = `awa-${suffix}@equipe.example.com`;
  const invited = await request.post(`${API}/platform/team/invitations`, {
    headers: {
      Authorization: `Bearer ${await apiToken(request)}`,
      "Idempotency-Key": crypto.randomUUID(),
    },
    data: { display_name: `Awa Ndiaye ${suffix}`, email, role: "administrator" },
  });
  expect(invited.status()).toBe(201);
  return { email, path: new URL((await invited.json()).invitation_url as string).pathname };
}

async function choosePassword(page: Page, path: string): Promise<void> {
  await page.goto(path);
  await page.getByLabel("Mot de passe", { exact: true }).fill(PASSWORD);
  await page.getByLabel("Le même, une seconde fois").fill(PASSWORD);
  await page.getByRole("button", { name: "Continuer" }).click();
}

async function passwordStep(page: Page, email: string): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("E-mail").fill(email);
  await page.getByLabel("Mot de passe", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Se connecter" }).click();
}

test("invitation : mot de passe, enrôlement, codes de secours, puis connexion en deux temps", async ({
  page,
  request,
}) => {
  const { email, path } = await invite(request);
  await choosePassword(page, path);

  // Aucune session avant le premier code : l'enrôlement, avec un code faux d'abord.
  await expect(page.getByRole("img", { name: /QR code à scanner/ })).toBeVisible();
  await axe(page, "enrôlement");
  await page.getByLabel("Code à 6 chiffres").fill("000000");
  await page.getByRole("button", { name: "Activer la double authentification" }).click();
  await expect(page.locator("form").getByRole("alert")).toContainText("Code incorrect");
  await page.getByLabel("Code à 6 chiffres").fill("");
  const { secret, codes } = await enrollOnScreen(page);
  await axe(page, "codes de secours");
  await expect(
    page.getByRole("button", { name: "Continuer vers l'administration" }),
  ).toBeDisabled();
  await keepCodesAndEnter(page);

  // Nouvelle connexion : le mot de passe ne suffit pas, le code ouvre la session.
  await page.context().clearCookies();
  await passwordStep(page, email);
  await expect(page.getByLabel("Code à 6 chiffres")).toBeVisible();
  await axe(page, "code");
  await page.getByLabel("Code à 6 chiffres").fill(await freshCode(secret));
  await page.getByRole("button", { name: "Valider" }).click();
  await expect(page.getByRole("heading", { name: "Tableau de bord" })).toBeVisible();

  // Un code de secours sert une fois ; la seconde, il est refusé.
  for (const attempt of ["accepté", "refusé"] as const) {
    await page.context().clearCookies();
    await passwordStep(page, email);
    await page.getByRole("button", { name: "Utiliser un code de secours" }).click();
    await page.getByLabel("Code de secours").fill(codes[0]!);
    await page.getByRole("button", { name: "Valider" }).click();
    if (attempt === "accepté") {
      await expect(page.getByRole("heading", { name: "Tableau de bord" })).toBeVisible();
    } else {
      await expect(page.locator("form").getByRole("alert")).toHaveText(
        "Code de secours incorrect ou déjà utilisé.",
      );
    }
  }
});

test("Ma sécurité : régénérer les codes de secours exige un code", async ({ page, request }) => {
  const { path } = await invite(request);
  await choosePassword(page, path);
  const { secret } = await enrollOnScreen(page);
  await keepCodesAndEnter(page);

  await page.getByRole("link", { name: "Ma sécurité" }).first().click();
  await expect(page.getByText("Codes de secours encore utilisables")).toContainText("10");
  await page.getByRole("button", { name: "Générer de nouveaux codes de secours" }).click();
  await page.getByLabel("Code de votre application").fill(await freshCode(secret));
  await page.getByRole("button", { name: "Générer de nouveaux codes", exact: true }).click();
  await expect(
    page.getByRole("list", { name: "Codes de secours" }).getByRole("listitem"),
  ).toHaveCount(10);
  await page.getByLabel("J'ai rangé ces codes en lieu sûr.").check();
  await page.getByRole("button", { name: "Terminé" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Nouveaux codes" })).toBeVisible();
});

test("téléphone perdu : un autre administrateur réinitialise, le collègue réenrôle", async ({
  page,
  browser,
  request,
}) => {
  const { email, path } = await invite(request);
  const context = await browser.newContext({ locale: "fr-FR", timezoneId: "Africa/Dakar" });
  const colleague = await context.newPage();
  await choosePassword(colleague, path);
  await enrollOnScreen(colleague);
  await keepCodesAndEnter(colleague);

  await signInAdmin(page);
  await page.goto("/team");
  const row = page.getByRole("row", { name: new RegExp(email) });
  await row.getByRole("button", { name: /Réinitialiser le code/ }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Raison").fill("Téléphone perdu");
  await dialog.getByRole("button", { name: /^Réinitialiser pour/ }).click();
  await expect(
    page.getByRole("status").filter({ hasText: "double authentification" }),
  ).toBeVisible();
  await expect(row.getByText("Code à activer")).toBeVisible();

  // Sa session est fermée ; à la connexion suivante, il enrôle à nouveau.
  await colleague.goto("/team");
  await expect(colleague).toHaveURL(/\/login/);
  await passwordStep(colleague, email);
  await expect(colleague.getByRole("img", { name: /QR code à scanner/ })).toBeVisible();
  await context.close();
});

for (const scheme of ["light", "dark"] as const) {
  test(`axe AA de la seconde étape et de « Ma sécurité », ${scheme === "light" ? "clair" : "sombre"}`, async ({
    page,
  }) => {
    await page.addInitScript((theme) => {
      window.localStorage.setItem("coges-admin:theme", theme);
    }, scheme);
    await signInAdmin(page);
    await page.goto("/security");
    await expect(page.getByText(/Codes de secours encore utilisables/)).toBeVisible();
    await axe(page, `/security ${scheme}`);
  });
}

test("360 px : enrôlement et codes de secours sans défilement horizontal", async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 360, height: 760 });
  const { path } = await invite(request);
  await choosePassword(page, path);
  await expect(page.getByRole("img", { name: /QR code à scanner/ })).toBeVisible();
  await noHorizontalScroll(page, "enrôlement");
  await enrollOnScreen(page);
  await noHorizontalScroll(page, "codes de secours");
  await keepCodesAndEnter(page);
  await page.goto("/security");
  await noHorizontalScroll(page, "/security");
});

test("le code calculé ici est celui de la RFC 6238", () => {
  // Annexe B, SHA-1, T = 59 s : 94287082 sur 8 chiffres, donc 287082 sur 6.
  expect(totp("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", 1)).toBe("287082");
});
