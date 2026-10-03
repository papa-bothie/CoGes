import { expect, test, type Page } from "@playwright/test";

import { DEMO, loginThroughUi } from "./fixtures";
import { settle } from "./screens";

/**
 * Cibles tactiles (ADR 0059) : sur tablette (`pointer: coarse`), toute cible interactive
 * visible mesure au moins 44 × 44 px — WCAG 2.5.5 et recommandations des plateformes. Sur
 * ordinateur, la densité compacte ne change pas (rien n'est mesuré ici).
 */
const MIN = 44;

test.use({ hasTouch: true, viewport: { width: 1024, height: 768 } });
test.describe.configure({ timeout: 90_000 });

const INTERACTIVE = [
  "button",
  "a[href]",
  "input:not([type=hidden])",
  "select",
  "textarea",
  "[role=button]",
  "[role=radio]",
  "[role=tab]",
  "[role=combobox]",
  "[role=checkbox]",
  "tr[tabindex]",
].join(",");

type Offender = { label: string; width: number; height: number };

/** Cibles visibles plus petites que 44 × 44 px, décrites pour le message d'échec. */
async function smallTargets(page: Page): Promise<Offender[]> {
  return page.locator(INTERACTIVE).evaluateAll((elements, min) => {
    const offenders: { label: string; width: number; height: number }[] = [];
    for (const element of elements) {
      const box = element.getBoundingClientRect();
      const style = getComputedStyle(element);
      const hidden =
        box.width === 0 ||
        box.height === 0 ||
        style.visibility === "hidden" ||
        style.display === "none" ||
        element.closest("[aria-hidden=true], [inert], .sr-only") !== null ||
        // Indicateur de développement de Next : absent en production.
        element.closest("nextjs-portal, [data-nextjs-dev-tools-button]") !== null ||
        (element.getAttribute("aria-label") ?? "").includes("Next.js Dev Tools");
      if (hidden) continue;
      // Une cible plus petite peut se trouver dans une plus grande qui reçoit le toucher
      // (bouton de tri dans un en-tête, case dans une ligne cliquable) : elle compte alors
      // pour la grande.
      const host = element.parentElement?.closest("button, a[href], label, tr[tabindex]");
      if (host && host !== element) {
        const outer = host.getBoundingClientRect();
        if (outer.width >= min && outer.height >= min) continue;
      }
      // Une case dans un <label> : toute l'étiquette reçoit le toucher.
      const label = element.closest("label");
      if (label) {
        const outer = label.getBoundingClientRect();
        if (outer.width >= min && outer.height >= min) continue;
      }
      if (box.width + 0.5 < min || box.height + 0.5 < min) {
        const name =
          element.getAttribute("aria-label") ??
          (element.textContent ?? "").trim().slice(0, 40) ??
          "";
        offenders.push({
          label: `<${element.tagName.toLowerCase()}> ${name || element.getAttribute("name") || element.id}`,
          width: Math.round(box.width),
          height: Math.round(box.height),
        });
      }
    }
    return offenders;
  }, MIN);
}

async function expectTouchFriendly(page: Page) {
  const offenders = await smallTargets(page);
  expect(
    offenders,
    offenders.map((o) => `${o.label} : ${o.width} × ${o.height}`).join("\n"),
  ).toEqual([]);
}

test.beforeEach(async ({ page }) => {
  await page.goto("/login");
  await loginThroughUi(page, DEMO);
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
  await expect(page.evaluate(() => matchMedia("(pointer: coarse)").matches)).resolves.toBe(true);
});

test("Nouvelle vente : saisie, ligne d'article et barre d'actions", async ({ page }) => {
  // Un article du catalogue de démonstration, toujours en stock (ADR 0060).
  const product = { name: "Sucre en poudre" };
  await page.goto("/sales/new");
  await settle(page);
  await page.getByRole("combobox", { name: "Ajouter un article (nom ou SKU)" }).fill(product.name);
  await page.getByRole("option", { name: new RegExp(product.name) }).click();
  await expect(page.getByRole("textbox", { name: `Quantité de ${product.name}` })).toBeVisible();
  await expectTouchFriendly(page);
});

test("Stock : onglets, lignes et pagination", async ({ page }) => {
  await page.goto("/inventory");
  await settle(page);
  await expectTouchFriendly(page);
});

test("Ventes : filtres, lignes cliquables et pagination", async ({ page }) => {
  await page.goto("/sales");
  await settle(page);
  await expectTouchFriendly(page);
});
