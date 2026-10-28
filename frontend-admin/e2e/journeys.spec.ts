import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

/**
 * Les tâches de l'administrateur (prompt 27, D1), chacune avec son nombre d'actions
 * MAXIMUM, compté ici : un clic ou une touche qui déclenche quelque chose. La saisie du
 * texte n'est pas comptée. Les chiffres « avant » sont dans
 * docs/design/captures/admin/avant/README.md.
 */
const ADMIN = { email: "admin@e2e.example.com", password: "admin-coges-e2e-2026" };
const API = "http://localhost:8100/api/v1";
const COLLEAGUE = { password: "demo-coges-2026" };

class Counter {
  count = 0;
  async act<T>(action: Promise<T>): Promise<T> {
    this.count += 1;
    return action;
  }
}

async function signIn(page: Page): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("E-mail").fill(ADMIN.email);
  await page.getByLabel("Mot de passe", { exact: true }).fill(ADMIN.password);
  await page.getByRole("button", { name: "Se connecter" }).click();
  await expect(page.getByRole("heading", { name: "Tableau de bord" })).toBeVisible();
}

async function axe(page: Page): Promise<void> {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  expect(results.violations).toEqual([]);
}

async function adminHeaders(request: APIRequestContext): Promise<Record<string, string>> {
  const login = await request.post(`${API}/platform/auth/login`, { data: ADMIN });
  expect(login.ok()).toBeTruthy();
  return { Authorization: `Bearer ${(await login.json()).access_token}` };
}

/** Un collègue créé par le vrai chemin : invitation (lien montré, sans SMTP), acceptation. */
async function colleague(
  request: APIRequestContext,
  role: "support" | "administrator" = "support",
): Promise<{ name: string; email: string }> {
  const suffix = crypto.randomUUID().slice(0, 6);
  const name = `Moussa Badji-${suffix}`;
  const email = `moussa-${suffix}@equipe.example.com`;
  const invited = await request.post(`${API}/platform/team/invitations`, {
    headers: { ...(await adminHeaders(request)), "Idempotency-Key": crypto.randomUUID() },
    data: { display_name: name, email, role },
  });
  expect(invited.status()).toBe(201);
  const url = (await invited.json()).invitation_url as string;
  const accepted = await request.post(`${API}/platform/auth/accept-invitation`, {
    data: { token: url.split("/invitation/")[1], password: COLLEAGUE.password },
  });
  expect(accepted.ok()).toBeTruthy();
  return { name, email };
}

test("1. retrouver une entreprise ou un collègue depuis n'importe quelle page : 2 actions", async ({
  page,
  request,
}) => {
  const mate = await colleague(request);
  await signIn(page);
  await page.goto("/system");

  const company = new Counter();
  await company.act(page.keyboard.press("/"));
  await page.keyboard.type("Parcours administration");
  await expect(page.getByRole("option", { name: /^Parcours administration/ })).toBeVisible();
  await company.act(page.keyboard.press("Enter"));
  await expect(page.getByRole("heading", { name: "Parcours administration" })).toBeVisible();
  expect(company.count).toBeLessThanOrEqual(2);

  const account = new Counter();
  await account.act(page.keyboard.press("/"));
  await page.keyboard.type(mate.name);
  await expect(page.getByRole("option", { name: new RegExp(mate.name) })).toBeVisible();
  await account.act(page.keyboard.press("Enter"));
  await expect(page.getByRole("row", { name: new RegExp(mate.name) })).toHaveAttribute(
    "aria-current",
    "true",
  );
  expect(account.count).toBeLessThanOrEqual(2);
});

test("2. suspendre puis réactiver un collègue : 3 clics + confirmation", async ({
  page,
  request,
}) => {
  const mate = await colleague(request);
  await signIn(page);
  const steps = new Counter();
  await steps.act(page.getByRole("link", { name: "Équipe", exact: true }).click());
  const row = page.getByRole("row", { name: new RegExp(mate.name) });
  await steps.act(row.getByRole("button", { name: /Suspendre/ }).click());
  const dialog = page.getByRole("dialog", { name: /Suspendre Moussa B\./ });
  await dialog.getByLabel("Raison").fill("Départ de l'équipe");
  await steps.act(dialog.getByRole("button", { name: /^Suspendre Moussa B\./ }).click());
  await expect(page.getByRole("status").filter({ hasText: "est suspendu" })).toBeVisible();
  await expect(row.getByText("Suspendu", { exact: true })).toBeVisible();
  expect(steps.count).toBeLessThanOrEqual(4);

  // L'accès du collègue est coupé.
  const refused = await request.post(`${API}/platform/auth/login`, {
    data: { email: mate.email, password: COLLEAGUE.password },
  });
  expect(refused.status()).toBe(401);

  // Réactiver : confirmation légère, sans raison.
  await row.getByRole("button", { name: /Réactiver/ }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: /^Réactiver Moussa B\./ })
    .click();
  await expect(row.getByText("Actif", { exact: true })).toBeVisible();
});

test("2. suspendre une entreprise : 3 clics + confirmation depuis sa fiche", async ({ page }) => {
  await signIn(page);
  await page.keyboard.press("/");
  await page.keyboard.type("Parcours administration");
  await expect(page.getByRole("option", { name: /^Parcours administration/ })).toBeVisible();
  await page.keyboard.press("Enter");
  const steps = new Counter();
  await steps.act(page.getByRole("button", { name: "Suspendre l'entreprise" }).click());
  const dialog = page.getByRole("dialog", { name: "Suspendre Parcours administration ?" });
  await dialog.getByLabel("Raison").fill("Parcours chronométré");
  await steps.act(
    dialog.getByRole("button", { name: "Suspendre Parcours administration" }).click(),
  );
  await expect(page.getByText("Suspendue", { exact: true })).toBeVisible();
  expect(steps.count).toBeLessThanOrEqual(4);
  await page.getByRole("button", { name: "Réactiver l'entreprise" }).click();
  await page.getByRole("button", { name: "Réactiver Parcours administration" }).click();
  await expect(page.getByText("Suspendue", { exact: true })).toHaveCount(0);
});

test("3. inviter un collègue : 4 champs au plus, 1 bouton, puis l'invitation complète", async ({
  page,
  browser,
}) => {
  await signIn(page);
  await page.goto("/team");
  const steps = new Counter();
  await steps.act(page.getByRole("button", { name: "Inviter un collègue" }).click());
  const dialog = page.getByRole("dialog", { name: "Inviter un collègue" });
  const fields = dialog.locator("input, select, textarea");
  expect(await fields.count()).toBeLessThanOrEqual(4);
  const suffix = crypto.randomUUID().slice(0, 6);
  const email = `fatou-${suffix}@equipe.example.com`;
  await dialog.getByLabel("Nom").fill(`Fatou Sow ${suffix}`);
  await dialog.getByLabel("E-mail").fill(email);
  await dialog.getByLabel("Profil").selectOption("administrator");
  await expect(dialog.getByText(/Administrateur : tout ce que fait le support/)).toBeVisible();
  await steps.act(dialog.getByRole("button", { name: "Envoyer l'invitation" }).click());
  expect(steps.count).toBeLessThanOrEqual(2);

  // Sans SMTP (parcours e2e), le lien est montré une fois : c'est l'envoi capturé.
  await expect(page.getByText(/E-mail non configuré/)).toBeVisible();
  const link = await page.locator("code").filter({ hasText: "/invitation/" }).innerText();
  await expect(page.getByRole("row", { name: new RegExp(`Fatou Sow ${suffix}`) })).toContainText(
    "Invité",
  );
  await axe(page);

  // Le collègue ouvre le lien, choisit son mot de passe et arrive au tableau de bord.
  const context = await browser.newContext({ locale: "fr-FR", timezoneId: "Africa/Dakar" });
  const invitee = await context.newPage();
  await invitee.goto(new URL(link).pathname);
  await expect(invitee.getByText(/Règle : 12 caractères au moins/)).toBeVisible();
  await axe(invitee);
  await invitee.getByLabel("Mot de passe", { exact: true }).fill(COLLEAGUE.password);
  await invitee.getByLabel("Le même, une seconde fois").fill(COLLEAGUE.password);
  await invitee.getByRole("button", { name: "Activer mon compte" }).click();
  await expect(invitee.getByRole("heading", { name: "Tableau de bord" })).toBeVisible();
  await expect(invitee.getByText(`Fatou Sow ${suffix} · Administrateur`).first()).toBeVisible();

  // Le même lien ne sert plus, avec un seul message.
  const again = await context.newPage();
  await context.clearCookies();
  await again.goto(new URL(link).pathname);
  await again.getByLabel("Mot de passe", { exact: true }).fill(COLLEAGUE.password);
  await again.getByLabel("Le même, une seconde fois").fill(COLLEAGUE.password);
  await again.getByRole("button", { name: "Activer mon compte" }).click();
  await expect(again.locator("form").getByRole("alert")).toHaveText(
    /Ce lien d'invitation n'est plus valable/,
  );
  await context.close();
});

test("4. changer le profil d'un collègue : 3 clics + confirmation, effectif aussitôt", async ({
  page,
  request,
}) => {
  const mate = await colleague(request);
  await signIn(page);
  const steps = new Counter();
  await steps.act(page.getByRole("link", { name: "Équipe", exact: true }).click());
  const row = page.getByRole("row", { name: new RegExp(mate.name) });
  await steps.act(row.getByRole("button", { name: /Changer le profil/ }).click());
  await steps.act(
    page
      .getByRole("dialog")
      .getByRole("button", { name: /^Passer Moussa B\. en Administrateur/ })
      .click(),
  );
  await expect(row).toContainText("Administrateur");
  expect(steps.count).toBeLessThanOrEqual(4);
});

test("5. qui a fait quoi : 2 clics depuis la fiche", async ({ page, request }) => {
  const mate = await colleague(request);
  await signIn(page);
  await page.goto("/team");
  const row = page.getByRole("row", { name: new RegExp(mate.name) });
  await row.getByRole("button", { name: /Changer le profil/ }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: /^Passer Moussa B\./ })
    .click();
  await expect(row).toContainText("Administrateur");

  const steps = new Counter();
  await steps.act(row.getByRole("link", { name: /Historique/ }).click());
  await expect(page.getByRole("heading", { name: "Journal" })).toBeVisible();
  await expect(page.getByText(/a passé Moussa B\. de Support à Administrateur/)).toBeVisible();
  expect(steps.count).toBeLessThanOrEqual(2);

  // Depuis la fiche d'une entreprise.
  await page.goto("/companies");
  await page.getByRole("link", { name: "Parcours administration" }).click();
  const fromCompany = new Counter();
  await fromCompany.act(page.getByRole("link", { name: "Historique" }).click());
  await expect(page.getByRole("heading", { name: "Journal" })).toBeVisible();
  await expect(page.getByRole("link", { name: /Entreprise : / })).toBeVisible();
  expect(fromCompany.count).toBeLessThanOrEqual(2);
  await axe(page);
});

test("6. ce qui demande une action se voit dès l'ouverture", async ({ page, request }) => {
  const headers = await adminHeaders(request);
  const companies = await request.get(`${API}/platform/companies`, {
    headers,
    params: { search: "support-e2e" },
  });
  const [shop] = (await companies.json()).items as [{ id: string; name: string }];
  await request.patch(`${API}/platform/companies/${shop.id}/status`, {
    headers,
    data: { status: "suspended", reason: "Parcours « À traiter »" },
  });
  try {
    await signIn(page);
    const block = page.getByRole("region", { name: "À traiter" });
    await expect(block).toContainText(`${shop.name} est suspendue`);
    // Les parcours e2e tournent sans worker : le bilan est en panne, et le dit.
    await expect(block).toContainText("Le système est en panne");
    await expect(page.getByText(/Compté le \d\d\/\d\d\/\d{4}/).first()).toBeVisible();
    await axe(page);
  } finally {
    await request.patch(`${API}/platform/companies/${shop.id}/status`, {
      headers,
      data: { status: "active", reason: "Fin du parcours" },
    });
  }
});

test("au clavier seul : inviter et suspendre", async ({ page }) => {
  await signIn(page);
  await page.goto("/team");
  await page.getByRole("button", { name: "Inviter un collègue" }).focus();
  await page.keyboard.press("Enter");
  const suffix = crypto.randomUUID().slice(0, 6);
  await page.keyboard.type(`Clavier ${suffix}`);
  await page.keyboard.press("Tab");
  await page.keyboard.type(`clavier-${suffix}@equipe.example.com`);
  await page.keyboard.press("Tab");
  await page.keyboard.press("Tab");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Envoyer l'invitation" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByText(/Invitation créée pour clavier-/)).toBeVisible();

  // Suspendre un collègue : Entrée, la raison, la confirmation, rien qu'au clavier.
  const row = page.getByRole("row", { name: /Équipe des parcours|Moussa Badji/ }).filter({
    has: page.getByRole("button", { name: /Suspendre/ }),
  });
  await row
    .first()
    .getByRole("button", { name: /Suspendre/ })
    .focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("button", { name: "Annuler" })).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(dialog.getByLabel("Raison")).toBeFocused();
  await page.keyboard.type("Au clavier seul");
  await page.keyboard.press("Tab");
  await page.keyboard.press("Tab");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("status").filter({ hasText: "est suspendu" })).toBeVisible();
  // Échap ferme le tiroir comme la fenêtre : rien n'a été laissé ouvert.
  await expect(dialog).toBeHidden();
});
