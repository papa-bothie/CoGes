import { expect, test } from "@playwright/test";

import { DEMO, E2E, loginThroughUi, managerApi } from "./fixtures";

/**
 * Lot 3e (ADR 0074) : une personne ajoutée par son téléphone reçoit un mot de passe
 * provisoire, se connecte avec son numéro tapé à sa façon, puis doit choisir le sien
 * avant toute autre chose ; « Tout marquer comme lu » vide le compteur d'alertes.
 */
test.describe.configure({ timeout: 90_000 });

test("connexion par téléphone, puis le mot de passe provisoire est remplacé", async ({
  page,
  request,
}) => {
  const client = await managerApi(request);
  const roles = await client.get("/roles?page_size=50");
  const seller = (roles.items as { id: string; name: string }[]).find(
    (role) => role.name === "vendeur",
  )!;
  const digits = `77${String(Date.now()).slice(-7)}`;
  const created = await client.post("/users", {
    full_name: "Modou Sène",
    phone: digits,
    role_ids: [seller.id],
  });
  expect(created.temporary_password).toMatch(/^[A-Z]+-\d{4}-[A-Z]+$/);

  await page.goto("/login");
  const spaced = `${digits.slice(0, 2)} ${digits.slice(2, 5)} ${digits.slice(5, 7)} ${digits.slice(7)}`;
  await loginThroughUi(page, {
    slug: E2E.slug,
    email: spaced,
    password: created.temporary_password,
  });
  await expect(page).toHaveURL(/\/password$/, { timeout: 30_000 });
  await expect(page.getByRole("heading", { name: "Choisissez votre mot de passe" })).toBeVisible();

  await page.getByLabel("Mot de passe reçu").fill(created.temporary_password);
  await page.getByLabel("Nouveau mot de passe", { exact: true }).fill("mon-mot-de-passe-a-moi");
  await page.getByLabel("Retapez le nouveau mot de passe").fill("mon-mot-de-passe-a-moi");
  await page.getByRole("button", { name: "Enregistrer et entrer" }).click();
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
  await expect(page.getByRole("heading", { level: 1, name: /^Bonjour / })).toBeVisible();
});

test("le mot de passe affiché se montre et se cache", async ({ page }) => {
  await page.goto("/login");
  const field = page.getByLabel("Mot de passe", { exact: true });
  await field.fill("secret-a-verifier");
  await expect(field).toHaveAttribute("type", "password");
  await page.getByRole("button", { name: "Afficher le mot de passe" }).click();
  await expect(field).toHaveAttribute("type", "text");
  await page.getByRole("button", { name: "Cacher le mot de passe" }).click();
  await expect(field).toHaveAttribute("type", "password");
});

test("« Tout marquer comme lu » vide le compteur", async ({ page, request }) => {
  // La démo reçoit les alertes de l'Intelligence, calculée à la remise à zéro.
  const client = await managerApi(request, DEMO);
  const unread = await client.get("/notifications/unread-count");
  test.skip(unread.unread === 0, "Aucune alerte non lue dans la démo.");
  await page.goto("/login");
  await loginThroughUi(page, DEMO);
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
  await page.goto("/notifications");
  await page.getByRole("button", { name: "Tout marquer comme lu" }).click();
  await expect(page.getByText("Tout est lu")).toBeVisible();
  expect((await client.get("/notifications/unread-count")).unread).toBe(0);
});
