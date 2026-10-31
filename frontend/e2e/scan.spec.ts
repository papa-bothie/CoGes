import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import {
  E2E,
  loginThroughUi,
  managerApi,
  managerToken,
  type Credentials,
  type ManagerApi,
} from "./fixtures";

/**
 * Entrée de stock par scan (prompt 33). La caméra passe par `getUserMedia` : Chromium reçoit
 * un faux périphérique (mire de test) et l'autorisation d'avance, comme un téléphone où le
 * commerçant a dit « Autoriser ».
 */
test.use({
  permissions: ["camera"],
  launchOptions: {
    args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"],
  },
});

test.describe.configure({ timeout: 90_000 });

test("S0 : la caméra est permise à la même origine, micro et position restent fermés", async ({
  page,
}) => {
  const response = await page.goto("/login");

  // Sous `camera=()`, le navigateur refuse la caméra avant même de demander à la personne.
  const camera = await page.evaluate(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true });
      stream.getTracks().forEach((track) => track.stop());
      return "ok";
    } catch (error) {
      return (error as Error).name;
    }
  });
  expect(camera).toBe("ok");

  const policy = response?.headers()["permissions-policy"] ?? "";
  expect(policy).toContain("camera=(self)");
  expect(policy).toContain("microphone=()");
  expect(policy).toContain("geolocation=()");
});

// ---------------------------------------------------------------------------------------
// Écran « Recevoir une livraison » (S2, S3) : vraie caméra de Chromium (mire de test), et un
// lecteur natif simulé qui « lit » le code que le test lui donne. Chrome pour Linux n'a pas
// `BarcodeDetector` ; c'est celui de Chrome Android qu'on imite.

/** Lecteur simulé et caméras ouvertes, posés avant tout script de la page. */
async function simulatedReader(page: Page) {
  await page.addInitScript(() => {
    const state = window as unknown as {
      __scanCode: string | null;
      __cameraTracks: MediaStreamTrack[];
      BarcodeDetector: unknown;
    };
    state.__scanCode = null;
    state.__cameraTracks = [];
    const getUserMedia = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    navigator.mediaDevices.getUserMedia = async (constraints) => {
      const stream = await getUserMedia(constraints);
      state.__cameraTracks.push(...stream.getTracks());
      return stream;
    };
    state.BarcodeDetector = class {
      async detect(video: HTMLVideoElement) {
        const code = state.__scanCode;
        if (!code || video.readyState < 2) return [];
        state.__scanCode = null;
        return [{ rawValue: code }];
      }
    };
  });
}

async function showToCamera(page: Page, code: string) {
  await page.evaluate((value) => {
    (window as unknown as { __scanCode: string }).__scanCode = value;
  }, code);
}

/** Toutes les pistes de caméra ouvertes sont arrêtées (aucune caméra qui reste allumée). */
async function cameraIsOff(page: Page) {
  await expect
    .poll(() =>
      page.evaluate(() =>
        (window as unknown as { __cameraTracks: MediaStreamTrack[] }).__cameraTracks.every(
          (track) => track.readyState === "ended",
        ),
      ),
    )
    .toBe(true);
}

async function cameraOpenings(page: Page): Promise<number> {
  return page.evaluate(
    () => (window as unknown as { __cameraTracks: MediaStreamTrack[] }).__cameraTracks.length,
  );
}

/** Un EAN-13 valide et neuf : préfixe 3, onze chiffres tirés, clé. */
function freshEan13(): string {
  const body = `3${String(Math.floor(Math.random() * 1e11)).padStart(11, "0")}`;
  const sum = [...body].reduce(
    (total, digit, index) => total + Number(digit) * (index % 2 ? 3 : 1),
    0,
  );
  return `${body}${(10 - (sum % 10)) % 10}`;
}

async function login(page: Page, credentials: Credentials = E2E) {
  await page.context().clearCookies();
  await page.goto("/login");
  await loginThroughUi(page, credentials);
  await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
}

async function supplierNamed(client: ManagerApi) {
  const name = `Grossiste scan ${crypto.randomUUID().slice(0, 6)}`;
  await client.post("/suppliers", { name });
  return name;
}

const created: string[] = [];

test.afterAll(async ({ request }) => {
  // Les comptes de ce fichier ne comptent plus dans le plafond d'utilisateurs (ADR 0091).
  const client = await managerApi(request);
  for (const id of created) await client.patch(`/users/${id}`, { is_active: false });
});

test("scan d'un article existant : il en reste 5, on en reçoit 20, il y en a 25", async ({
  page,
  request,
}) => {
  const client = await managerApi(request);
  const code = freshEan13();
  const { product } = await client.post("/inventory/products", {
    name: `Riz scan ${code.slice(-5)}`,
    unit: "sac",
    barcode: code,
    unit_price: "15500",
    cost_price: "100",
    opening_qty: "5",
  });
  const supplier = await supplierNamed(client);
  await simulatedReader(page);
  await login(page);
  await page.goto("/inventory/receive");
  await page.getByRole("button", { name: supplier, exact: true }).click();

  await showToCamera(page, code);
  await page.getByRole("button", { name: "Scanner un article" }).click();
  const qty = page.getByLabel(`Quantité : ${product.name}`);
  await expect(qty).toHaveValue("1");
  await expect(qty).toBeFocused();
  await expect(page.getByText("En stock : 5 sacs")).toBeVisible();
  await expect(page.getByLabel(`Prix d'achat (F) : ${product.name}`)).toHaveValue("100");
  await cameraIsOff(page);
  await expect(page.getByRole("dialog")).toBeHidden();

  // Le même code une seconde fois : une pièce de plus, pas de doublon.
  await showToCamera(page, code);
  await page.getByRole("button", { name: "Scanner l'article suivant" }).click();
  await expect(qty).toHaveValue("2");
  await expect(page.getByText(/était déjà sur la livraison/)).toBeVisible();
  await cameraIsOff(page);

  await qty.fill("20");
  await page.getByLabel(`Prix d'achat (F) : ${product.name}`).fill("120");
  await expect(page.getByRole("list", { name: "Après la livraison" })).toHaveText(
    `${product.name} : 5 → 25`,
  );
  // Rien n'a bougé avant la validation.
  expect((await client.get(`/inventory/stock?product_id=${product.id}`)).items[0].qty_on_hand).toBe(
    "5.000",
  );
  await page.getByRole("button", { name: "Tout maintenant", exact: true }).click();
  await page.getByRole("button", { name: "Enregistrer la livraison" }).click();
  await expect(page.getByRole("heading", { name: "Livraison enregistrée" })).toBeVisible();

  const [line] = (await client.get(`/inventory/stock?product_id=${product.id}`)).items;
  expect(line.qty_on_hand).toBe("25.000");
  // 5 à 100 F + 20 à 120 F : 116 F, le prix d'achat de la fiche reste 100 F.
  expect(line.avg_cost).toBe("116.0000");
  expect((await client.get(`/products/${product.id}`)).cost_price).toBe("100.0000");
});

test("douchette : le code tapé puis Entrée ajoute la ligne, sans ouvrir la caméra", async ({
  page,
  request,
}) => {
  const client = await managerApi(request);
  const code = freshEan13();
  const { product } = await client.post("/inventory/products", {
    name: `Huile scan ${code.slice(-5)}`,
    barcode: code,
    unit_price: "1500",
    cost_price: "1100",
    opening_qty: "3",
  });
  await simulatedReader(page);
  await login(page);
  await page.goto("/inventory/receive");
  await page.getByRole("searchbox", { name: "Chercher un autre article" }).pressSequentially(code);
  await page.keyboard.press("Enter");
  await expect(page.getByLabel(`Quantité : ${product.name}`)).toHaveValue("1");
  expect(await cameraOpenings(page)).toBe(0);
});

test("article inconnu : créé à zéro, puis reçu une seule fois par la livraison", async ({
  page,
  request,
}) => {
  const client = await managerApi(request);
  const code = freshEan13();
  const name = `Lait scan ${code.slice(-5)}`;
  const supplier = await supplierNamed(client);
  await simulatedReader(page);
  await login(page);
  await page.goto("/inventory/receive");
  await page.getByRole("button", { name: supplier, exact: true }).click();

  await showToCamera(page, code);
  await page.getByRole("button", { name: "Scanner un article" }).click();
  await expect(page.getByText("Cet article n'existe pas encore. Le créer ?")).toBeVisible();
  await expect(page.getByText(`Code-barres : ${code}`)).toBeVisible();
  await cameraIsOff(page);
  await page.getByRole("button", { name: "Créer l'article" }).click();

  const dialog = page.getByRole("dialog", { name: "Nouvel article" });
  await expect(dialog.getByText(`Code-barres : ${code}`)).toBeVisible();
  await dialog.getByLabel("Nom de l'article").fill(name);
  await dialog.getByLabel("Prix de vente (F)").fill("650");
  await dialog.getByLabel("Prix d'achat (F)").fill("500");
  await dialog.getByLabel("Quantité reçue").fill("12");
  await dialog.getByRole("button", { name: "Créer et ajouter à la livraison" }).click();
  await expect(dialog).toBeHidden();

  await expect(page.getByLabel(`Quantité : ${name}`)).toHaveValue("12");
  await expect(page.getByLabel(`Prix d'achat (F) : ${name}`)).toHaveValue("500");
  await expect(page.getByRole("list", { name: "Après la livraison" })).toHaveText(
    `${name} : 0 → 12`,
  );
  await page.getByRole("button", { name: "Plus tard", exact: true }).click();
  await page.getByRole("button", { name: "Enregistrer la livraison" }).click();
  await expect(page.getByRole("heading", { name: "Livraison enregistrée" })).toBeVisible();

  const found = await client.get(`/inventory/products/by-barcode/${code}`);
  expect(found.qty_on_hand).toBe("12.000");
  // Une seule entrée : celle de la livraison, rattachée au fournisseur (aucun stock d'ouverture).
  const movements = await client.get(`/inventory/movements?product_id=${found.product_id}`);
  expect(movements.items.map((item: { type: string }) => item.type)).toEqual(["purchase_in"]);
  expect(movements.items[0].qty_delta).toBe("12.000");
});

test("sans le droit de créer un article : le gérant est nommé, rien n'est créé", async ({
  page,
  request,
}) => {
  const client = await managerApi(request);
  // Un magasinier : il reçoit les livraisons, mais ne crée pas d'article.
  const role = await client.post("/roles", {
    name: `Magasinier ${Date.now()}`,
    permissions: [
      "dashboard:read",
      "notifications:read",
      "products:read",
      "categories:read",
      "inventory:read",
      "inventory:create",
      "suppliers:read",
      "debts:create",
    ],
  });
  const email = `magasinier-${Date.now()}@${E2E.slug}.example.com`;
  const password = E2E.password;
  const person = await client.post("/users", {
    email,
    full_name: "Magasinier",
    password,
    role_ids: [role.id],
  });
  created.push(person.id);
  const code = freshEan13();

  await simulatedReader(page);
  await login(page, { slug: E2E.slug, email, password });
  await page.goto("/inventory/receive");
  await page.getByRole("searchbox", { name: "Chercher un autre article" }).fill(code);
  await page.keyboard.press("Enter");
  await expect(
    page.getByText("Cet article n'existe pas. Demandez au gérant de le créer."),
  ).toBeVisible();
  await expect(page.getByText(`Code-barres : ${code}`)).toBeVisible();
  await expect(page.getByRole("button", { name: "Créer l'article" })).toHaveCount(0);
  const lookup = await page.request.get(`/api/v1/inventory/products/by-barcode/${code}`, {
    headers: { Authorization: `Bearer ${await managerToken(request)}` },
  });
  expect(lookup.status()).toBe(404);
});

test("« Nouvel article » : le scan par la caméra remplit le code-barres", async ({ page }) => {
  const code = freshEan13();
  await simulatedReader(page);
  await login(page);
  await page.goto("/products/new");
  await showToCamera(page, code);
  await page.getByRole("button", { name: "Scanner le code-barres" }).click();
  await expect(page.getByText(`Code-barres : ${code}`)).toBeVisible();
  expect(await cameraOpenings(page)).toBeGreaterThan(0);
  await cameraIsOff(page);
});

test("écran de livraison après un scan : axe sans violation, 360 px sans défilement", async ({
  page,
  request,
}) => {
  const client = await managerApi(request);
  const code = freshEan13();
  const { product } = await client.post("/inventory/products", {
    name: `Sucre scan ${code.slice(-5)}`,
    barcode: code,
    unit_price: "900",
    cost_price: "700",
    opening_qty: "4",
  });
  await simulatedReader(page);
  await login(page);
  await page.goto("/inventory/receive");
  const search = page.getByRole("searchbox", { name: "Chercher un autre article" });
  await search.fill(code);
  await page.keyboard.press("Enter");
  await expect(page.getByLabel(`Quantité : ${product.name}`)).toHaveValue("1");
  await search.fill(freshEan13());
  await page.keyboard.press("Enter");
  await expect(page.getByText("Cet article n'existe pas encore. Le créer ?")).toBeVisible();

  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();
    expect(results.violations, scheme).toEqual([]);
  }

  await page.setViewportSize({ width: 360, height: 780 });
  await expect(page.getByRole("button", { name: "Scanner l'article suivant" })).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
});
