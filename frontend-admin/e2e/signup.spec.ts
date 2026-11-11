import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { API, signInAdmin } from "./mfa";

/**
 * Demandes d'inscription (lot 30, ADR 0118) : une demande sans e-mail arrive dans la file de
 * l'équipe, qui la voit, l'ouvre ; le commerçant se connecte alors avec son numéro.
 */
test.describe.configure({ timeout: 120_000 });

const PASSWORD = ["ma", "quincaillerie", "2026"].join("-");

async function axe(page: Page): Promise<void> {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  expect(results.violations).toEqual([]);
}

test("une demande sans e-mail : file de l'équipe, ouverture, puis connexion par le numéro", async ({
  page,
  request,
}) => {
  const marker = `${Date.now()}`.slice(-7);
  const shop = `Quincaillerie Admin ${marker}`;
  const phone = `+221 78 ${marker.slice(0, 3)} ${marker.slice(3, 5)} ${marker.slice(5)}`;
  const created = await request.post(`${API}/auth/signup-requests`, {
    data: {
      shop_name: shop,
      full_name: "Moussa Fall",
      phone,
      password: PASSWORD,
      accept_legal: true,
    },
  });
  expect(created.status()).toBe(202);
  expect((await created.json()).path).toBe("team");

  await signInAdmin(page);
  // Le tableau de bord et le menu comptent la file.
  await expect(page.getByRole("link", { name: /demandes? d'inscription à traiter/ })).toBeVisible();
  const navigation = page.getByRole("navigation", { name: "Navigation principale" });
  await expect(navigation.getByRole("link", { name: /Demandes \d+ à traiter/ })).toBeVisible();

  await navigation.getByRole("link", { name: /Demandes/ }).click();
  await expect(page.getByRole("heading", { name: "Demandes d'inscription" })).toBeVisible();
  await axe(page);
  await page.getByRole("link", { name: shop }).click();
  await expect(page.getByRole("heading", { level: 1, name: shop })).toBeVisible();
  await expect(page.getByText("À traiter par l'équipe")).toBeVisible();
  const whatsapp = page.getByRole("link", { name: "Écrire sur WhatsApp" });
  await expect(whatsapp).toHaveAttribute("href", /^https:\/\/wa\.me\/22178\d{7}\?text=/);
  await expect(page.getByRole("link", { name: "Appeler" })).toHaveAttribute(
    "href",
    /^tel:\+22178\d{7}$/,
  );
  await axe(page);

  await page.getByRole("button", { name: "Ouvrir la boutique" }).click();
  await page.getByRole("button", { name: `Ouvrir « ${shop} »` }).click();
  const notice = page.getByRole("status").filter({ hasText: "La boutique est ouverte" });
  await expect(notice).toBeVisible();
  const slug = (await notice.textContent())?.match(/Code : ([a-z0-9-]+)/)?.[1] ?? "";
  expect(slug).toMatch(/^quincaillerie-admin-/);
  const access = page.getByRole("link", { name: "Envoyer l'accès sur WhatsApp" });
  const href = decodeURIComponent((await access.getAttribute("href")) ?? "");
  expect(href).toContain(`boutique=${slug}`);
  expect(href).not.toContain(PASSWORD);
  await expect(page.getByRole("button", { name: "Ouvrir la boutique" })).toHaveCount(0);

  // Le commerçant se connecte avec son numéro et le mot de passe qu'il a choisi.
  const login = await request.post(`${API}/auth/login`, {
    data: { company_slug: slug, identifier: phone, password: PASSWORD },
  });
  expect(login.status()).toBe(200);
});
