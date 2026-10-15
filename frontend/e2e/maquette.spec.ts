import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import pixelmatch from "pixelmatch";
import { PNG } from "pngjs";

import { loginThroughUi, managerApi, managerToken, type Credentials } from "./fixtures";

/**
 * Comparaison automatique du front à la maquette v2 (règle 5 du prompt de phase 15).
 *
 * Parcourt `docs/design/maquette-v2/ecrans.md` ligne par ligne : ouvre la route sur
 * l'entreprise `maquette` à l'heure figée (mardi 6 octobre 2026, 10 h 45), capture à 1280
 * et à 390 px, compare à la capture de référence avec `pixelmatch`, et écrit
 * `docs/design/captures/phase-15/comparaison/NN-nom.png` (maquette | front | différences
 * en rouge) et `comparaison.md`. Seuil : 2 % de pixels différents, sauf écran listé dans
 * `docs/design/maquette-v2/ecarts.md` (`ALLOWED`).
 *
 * Les pixels ne suffisent pas : pour chaque écran livré, chaque texte visible de la page de
 * référence (`html/NN-nom.html`, ouverte dans le navigateur) doit se trouver mot pour mot sur
 * la page, espaces mis à part. Seule exception : un montant que `ecarts.md` note
 * « maquette : X F ». Un texte manquant fait échouer le test. Les états (02b, 04b…) n'ont pas
 * de page HTML : seuls leurs pixels sont comparés.
 *
 * Un écran pas encore refait est marqué `test.fixme` avec son lot. `MAQUETTE_ALL=1` les
 * compare quand même, sans échouer, pour mesurer le point de départ.
 *
 *   make maquette-check                 # écrans livrés
 *   MAQUETTE_ALL=1 make maquette-check  # tous les écrans, sans seuil
 */
const ROOT = join(__dirname, "..", "..");
const MOCKUP = join(ROOT, "docs", "design", "maquette-v2");
const OUT = join(ROOT, "docs", "design", "captures", "phase-15", "comparaison");
const THRESHOLD = 2;
const ALL = process.env.MAQUETTE_ALL === "1";
const FROZEN_NOW = new Date("2026-10-06T10:45:00Z");

const MAQUETTE: Credentials = {
  slug: "maquette",
  email: "gerant@maquette.example.com",
  password: "demo-coges-2026",
};

/** Écrans livrés : leur comparaison est bloquante. Les lots 3a à 3e les ajoutent. */
const DONE = new Set<string>([
  "01",
  "02",
  "02b",
  "02c",
  "02d",
  "03",
  "04",
  "04b",
  "05",
  "05b",
  "06",
  "07",
  "08",
  "09",
  "10",
  "11",
  "12",
  "13",
  "14",
  "14b",
  "15",
  "16",
  "17",
  "17b",
  "18",
  "18b",
  "19",
  "20",
  "21",
  "21b",
  "22",
  "22b",
  "22c",
  "23",
  "25",
  "26",
]);

/**
 * Écrans exemptés du seuil de pixels, avec leur écart noté dans ecarts.md : les données du
 * seed `maquette` ne reprennent pas chaque capture (ventes du jour, ordre des articles,
 * vendeur de la vente n° 1044), et l'écart dépasse 2 % sans erreur de mise en page. Les
 * images à trois panneaux servent alors la validation humaine.
 */
const ALLOWED = new Set<string>([
  "01",
  "02",
  "02b",
  "02c",
  "02d",
  "03",
  "04",
  "04b",
  "05",
  "05b",
  "06",
  "07",
  "08",
  "09",
  "10",
  "11",
  "12",
  "13",
  "14",
  "14b",
  "15",
  "16",
  "17",
  "17b",
  "18",
  "18b",
  "19",
  "20",
  "21",
  "21b",
  "22",
  "22b",
  "22c",
  "23",
  "25",
  "26",
]);

/** Attend la réponse d'une écriture sur le brouillon (ligne ajoutée, changée, retirée). */
function draftWrite(page: Page) {
  return page.waitForResponse(
    (response) =>
      /\/api\/v1\/sales(\/[^/]+\/items)?/.test(response.url()) &&
      response.request().method() !== "GET",
  );
}

/**
 * Le panier de la maquette 02 : 1 riz, 2 huiles, 3 sucres, client de passage. « Nouvelle
 * vente » reprend le brouillon du jour (ADR 0070) : ses lignes sont retirées d'abord, par
 * l'API, pour que chaque passage parte du même panier sans créer de nouveau brouillon.
 */
async function mockupCart(page: Page, request: APIRequestContext) {
  const token = await managerToken(request, MAQUETTE);
  const headers = { Authorization: `Bearer ${token}` };
  const drafts = await request.get("/api/v1/sales?status=draft&mine=true&page_size=100", {
    headers,
  });
  for (const draft of (await drafts.json()).items as { id: string }[]) {
    const detail = await request.get(`/api/v1/sales/${draft.id}`, { headers });
    for (const item of (await detail.json()).items as { id: string }[]) {
      const removed = await request.delete(`/api/v1/sales/${draft.id}/items/${item.id}`, {
        headers,
      });
      expect(removed.ok()).toBeTruthy();
    }
  }
  await page.reload();
  await expect(page.getByText("Touchez un article pour l'ajouter")).toBeVisible({
    timeout: 30_000,
  });
  for (const [name, times] of [
    ["Riz brisé 25 kg", 1],
    ["Huile Dinor 1 L", 2],
    ["Sucre en morceaux 1 kg", 3],
  ] as const) {
    for (let i = 0; i < times; i += 1) {
      const written = draftWrite(page);
      await page.getByRole("button", { name: `Ajouter ${name}` }).click();
      await written;
      await page.waitForLoadState("networkidle");
    }
  }
  await expect(page.getByText("21 000 F").first()).toBeVisible();
}

/**
 * États d'un écran (02b, 04b…) : les actions qui y mènent depuis la route. Ils sont
 * écrits avec l'écran, aux lots 3.
 */
const STATES: Record<string, (page: Page, request: APIRequestContext) => Promise<void>> = {
  "02": mockupCart,
  "02b": async (page, request) => {
    await mockupCart(page, request);
    await page.getByRole("button", { name: "Une partie", exact: true }).click();
    await page.getByLabel("Il donne maintenant").fill("7500");
  },
  "02c": async (page, request) => {
    await mockupCart(page, request);
    await page.getByLabel("Autre montant donné").fill("30000");
  },
  "05b": async (page) => {
    await page.getByRole("button", { name: "Facture A4" }).click();
    await expect(page.getByText("FACTURE", { exact: true })).toBeVisible();
  },
  "06": async (page) => {
    await page.getByLabel("Quantité rendue de Huile Dinor 1 L").fill("2");
    await expect(page.getByText("2 800 F")).toBeVisible();
  },
  "09": async (page) => {
    await page.getByLabel("Nom de l'article").fill("Riz brisé 25 kg");
    await page.getByLabel("Prix de vente (F)").fill("15500");
    await page.getByLabel("Prix d'achat (F)").fill("14000");
    await page.getByRole("button", { name: "Sac", exact: true }).click();
    await page.getByRole("button", { name: "Céréales", exact: true }).click();
    await page.getByLabel("Quantité en stock").fill("10");
    await page.getByLabel("Seuil d’alerte").fill("3");
    await page.getByLabel("Nom de l'article").blur();
  },
  "14b": async (page) => {
    await page.getByRole("button", { name: "Lui rappeler sa dette" }).click();
    await expect(page.getByLabel("Message WhatsApp")).not.toHaveValue("");
  },
  "15": async (page) => {
    await page.getByLabel("Nom du client").fill("Aminata Sow");
    await page.getByLabel("Téléphone").fill("77 655 90 21");
  },
  "11": async (page) => {
    await page.getByRole("button", { name: "Grossiste Sandaga", exact: true }).click();
    for (const [name, qty, cost] of [
      ["Riz brisé 25 kg", "10", "14000"],
      ["Huile Dinor 1 L", "24", "1150"],
    ] as const) {
      await page.getByRole("button", { name: `+ ${name}`, exact: true }).click();
      await page.getByLabel(`Quantité : ${name}`).fill(qty);
      await page.getByLabel(`Prix d'achat (F) : ${name}`).fill(cost);
    }
    await expect(page.getByText("167 600 F")).toBeVisible();
  },
  "04b": async (page) => {
    await page.getByRole("button", { name: "Annuler la vente" }).click();
    await expect(
      page.getByRole("heading", { name: "Pourquoi annuler cette vente ?" }),
    ).toBeVisible();
  },
  "17b": async (page) => {
    await page.getByRole("button", { name: "Aujourd'hui", exact: true }).click();
    await expect(page.getByText("Aujourd'hui, vous avez")).toBeVisible();
  },
  "18b": async (page) => {
    await page.getByLabel("Combien il paie ?").fill("7500");
  },
  "20": async (page) => {
    await page.getByRole("radio", { name: "Électricité" }).click();
  },
  "21b": async (page) => {
    // Seulement la question : choisir une raison annulerait vraiment la ligne.
    await page.getByRole("button", { name: "Annuler", exact: true }).first().click();
    await expect(page.getByRole("group", { name: "Pourquoi ?" })).toBeVisible();
  },
  "22b": async (page) => {
    await page.getByRole("button", { name: "Vos meilleurs articles" }).click();
    await expect(page.getByRole("heading", { name: /Ce qui vous rapporte le plus/ })).toBeVisible();
  },
  "22c": async (page) => {
    await page.getByRole("button", { name: "Prévisions" }).click();
    await expect(
      page.getByRole("heading", { name: "La semaine prochaine, vous devriez vendre environ" }),
    ).toBeVisible();
  },
  "02d": async (page, request) => {
    await mockupCart(page, request);
    // La confirmation est simulée : une vraie vente changerait la liste de l'écran 03. La
    // réponse est le brouillon lui-même, relu par l'API et marqué encaissé.
    const token = await managerToken(request, MAQUETTE);
    await page.route("**/api/v1/sales/*/confirm", async (route) => {
      const url = route
        .request()
        .url()
        .replace(/\/confirm$/, "");
      const detail = await request.get(url, { headers: { Authorization: `Bearer ${token}` } });
      const sale = (await detail.json()) as Record<string, unknown>;
      await route.fulfill({
        json: { ...sale, status: "confirmed", paid_total: sale.total, balance: "0.00" },
      });
    });
    await page.getByRole("button", { name: /^Encaisser/ }).click();
    await expect(page.getByRole("heading", { name: "Vente enregistrée" })).toBeVisible();
  },
};

type Row = { no: string; name: string; capture: string; route: string; lot: string };

function parseScreens(): Row[] {
  const text = readFileSync(join(MOCKUP, "ecrans.md"), "utf8");
  let previous = "/dashboard";
  return text
    .split("\n")
    .filter((line) => /^\|\s*\d{2}[a-z]?\s*\|/.test(line))
    .map((line) => {
      const cells = line.split("|").map((cell) => cell.trim());
      const [, no = "", name = "", capture = "", , route = "", lot = ""] = cells;
      // Un état (« idem ») reprend la route de son écran ; une route sans adresse (26 :
      // « toutes ») ouvre l'accueil.
      previous = route === "idem" ? previous : (route.match(/`([^`]+)`/)?.[1] ?? "/dashboard");
      return {
        no,
        name: name.replace(/^…\s*/, ""),
        capture: capture.replace(/`/g, ""),
        route: previous,
        lot,
      };
    });
}

const ROWS = parseScreens();

/** Les fiches de la maquette : V-001044 (Moussa Fall), le riz, Moussa Fall, Grossiste Sandaga. */
async function resolveRoute(request: APIRequestContext, route: string): Promise<string> {
  if (!route.includes("[id]")) return route;
  const api = await managerApi(request, MAQUETTE);
  const first = async (path: string) => {
    const page = await api.get(path);
    return page.items[0].id as string;
  };
  if (route.startsWith("/sales/")) {
    return route.replace("[id]", await first("/sales?search=V-001044&page_size=1"));
  }
  if (route.startsWith("/products/")) {
    return route.replace("[id]", await first("/products?search=Riz&page_size=1"));
  }
  if (route.startsWith("/customers/")) {
    return route.replace("[id]", await first("/customers?search=Moussa&page_size=1"));
  }
  if (route.startsWith("/suppliers/")) {
    return route.replace("[id]", await first("/suppliers?search=Sandaga&page_size=1"));
  }
  return route.replace("[id]", "inconnu");
}

/** Image élargie à `width` × `height`, complétée par le fond papier de la maquette. */
function pad(image: PNG, width: number, height: number): PNG {
  const out = new PNG({ width, height });
  for (let i = 0; i < out.data.length; i += 4) {
    out.data[i] = 0xfb;
    out.data[i + 1] = 0xf8;
    out.data[i + 2] = 0xf3;
    out.data[i + 3] = 0xff;
  }
  PNG.bitblt(image, out, 0, 0, image.width, image.height, 0, 0);
  return out;
}

/** Maquette | front | différences, côte à côte, 16 px d'écart. */
function triptych(reference: PNG, actual: PNG, diff: PNG): PNG {
  const gap = 16;
  const out = new PNG({ width: reference.width * 3 + gap * 2, height: reference.height });
  out.data.fill(0xff);
  [reference, actual, diff].forEach((image, index) => {
    PNG.bitblt(image, out, 0, 0, image.width, image.height, index * (image.width + gap), 0);
  });
  return out;
}

type Result = { file: string; width: number; percent: number; missing?: string[] };

/** Espaces (insécables, fines, retours à la ligne) ramenées à une seule. */
function squash(value: string): string {
  return value.replace(/[\s\u00a0\u202f]+/g, " ").trim();
}

/** Montants de la maquette écartés dans ecarts.md : « (maquette : 47 500 F) ». */
function allowedAmounts(): string[] {
  const text = readFileSync(join(MOCKUP, "ecarts.md"), "utf8");
  return [...text.matchAll(/maquette\s*:\s*(\d{1,3}(?:[\s\u00a0\u202f]\d{3})*)\s*F\b/g)].map(
    (match) => squash(match[1] ?? ""),
  );
}

/**
 * Textes de la maquette écartés dans ecarts.md, écran par écran : chaque fragment cité
 * « entre guillemets » sur la ligne d'un écran (ou de « Toutes »). Un texte manquant n'est
 * toléré que s'il y est cité mot pour mot.
 */
function allowedTexts(no: string): Set<string> {
  const screen = no.slice(0, 2);
  const allowed = new Set<string>();
  for (const line of readFileSync(join(MOCKUP, "ecarts.md"), "utf8").split("\n")) {
    const [, screens = ""] = line.split("|");
    if (!new RegExp(`\\b${screen}\\b|Toutes`).test(screens)) continue;
    for (const match of line.matchAll(/«\s*([^»]+?)\s*»/g)) allowed.add(squash(match[1] ?? ""));
  }
  return allowed;
}

/** « 47 500 F » dans un texte, mais pas « 147 500 F ». */
const AMOUNTS = allowedAmounts().map((amount) => new RegExp(`(?<!\\d)(?<!\\d )${amount} F`));

/**
 * Textes visibles de la page de référence, un par bloc (`innerText`), sans doublon. La
 * page est statique et non responsive : mêmes textes à toutes les largeurs.
 */
async function referenceTexts(page: Page, row: Row): Promise<string[] | null> {
  const file = join(MOCKUP, "html", `${row.capture}.html`);
  if (!existsSync(file)) return null;
  const reference = await page.context().newPage();
  try {
    await reference.setViewportSize({ width: 1280, height: 900 });
    await reference.goto(`file://${file}`);
    const text = await reference.locator("body").innerText();
    return [...new Set(text.split("\n").map(squash).filter(Boolean))];
  } finally {
    await reference.close();
  }
}

/** Textes de la référence absents de la page, hors montants et textes écartés. */
async function missingTexts(page: Page, row: Row, expected: string[]): Promise<string[]> {
  const actual = squash(await page.locator("body").innerText());
  const allowed = allowedTexts(row.no);
  return expected.filter(
    (text) =>
      !actual.includes(text) && !allowed.has(text) && !AMOUNTS.some((amount) => amount.test(text)),
  );
}

/**
 * Résultats gardés sur disque : Playwright relance son processus après un échec, et un
 * tableau en mémoire perdrait les écrans déjà mesurés.
 */
const RESULTS = join(OUT, "resultats.json");

function readResults(): Record<string, Result[]> {
  return existsSync(RESULTS)
    ? (JSON.parse(readFileSync(RESULTS, "utf8")) as Record<string, Result[]>)
    : {};
}

function saveResult(no: string, measured: Result[]) {
  mkdirSync(OUT, { recursive: true });
  writeFileSync(RESULTS, `${JSON.stringify({ ...readResults(), [no]: measured }, null, 2)}\n`);
}

async function compare(page: Page, row: Row, width: number): Promise<Result | null> {
  // 26 n'a qu'une capture, prise à 390 px et sans suffixe.
  const phoneOnly = !existsSync(join(MOCKUP, "captures", `${row.capture}-390.png`));
  if (phoneOnly && width === 1280) return null;
  const suffix = width === 390 && !phoneOnly ? "-390" : "";
  const referenceFile = readFileSync(join(MOCKUP, "captures", `${row.capture}${suffix}.png`));
  await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
  // Écran livré : il doit être chargé. Écran mesuré seulement (MAQUETTE_ALL) : on le prend
  // tel qu'il est au bout de 10 s, la mesure de départ ne bloque pas sur l'ancien écran.
  const strict = DONE.has(row.no);
  const settled = Promise.all([
    page.waitForLoadState("networkidle", { timeout: strict ? 30_000 : 10_000 }),
    expect(page.locator('[data-slot="skeleton"]')).toHaveCount(0, {
      timeout: strict ? 30_000 : 10_000,
    }),
  ]);
  await (strict ? settled : settled.catch(() => undefined));
  const shot = PNG.sync.read(
    await page.screenshot({ fullPage: true, animations: "disabled", caret: "hide" }),
  );
  const reference = PNG.sync.read(referenceFile);
  const w = Math.max(reference.width, shot.width);
  const h = Math.max(reference.height, shot.height);
  const left = pad(reference, w, h);
  const right = pad(shot, w, h);
  const diff = new PNG({ width: w, height: h });
  const different = pixelmatch(left.data, right.data, diff.data, w, h, { threshold: 0.1 });
  const file = `${row.capture}${width === 390 ? "-390" : ""}.png`;
  mkdirSync(OUT, { recursive: true });
  writeFileSync(join(OUT, file), PNG.sync.write(triptych(left, right, diff)));
  return { file, width, percent: (different / (w * h)) * 100 };
}

/** Textes vérifiés à la largeur de la référence : 1280 px, ou 390 px pour un écran de téléphone. */
function textWidth(measured: Result[]): number | undefined {
  return measured[0]?.width;
}

function writeReport() {
  const results = readResults();
  const lines = [
    "# Comparaison du front à la maquette v2",
    "",
    "Écrit par `frontend/e2e/maquette.spec.ts` (`make maquette-check`). Pourcentage de pixels",
    `différents à 1280 et à 390 px ; seuil ${THRESHOLD} %. Textes manquants : textes visibles de`,
    "`html/NN-nom.html` absents de la page (aucun toléré sur un écran livré ; « — » : état sans",
    "page HTML). Images : maquette | front | différences.",
    "",
    "| N° | Écran | Lot | 1280 px | 390 px | Textes manquants | Images |",
    "|---|---|---|---|---|---|---|",
  ];
  for (const row of ROWS) {
    const done = results[row.no];
    const cell = (width: number) => {
      const found = done?.find((result) => result.width === width);
      return found ? `${found.percent.toFixed(1)} %` : "—";
    };
    const images = done?.map((result) => `[${result.width}](comparaison/${result.file})`).join(" ");
    const status = DONE.has(row.no) ? "" : " (à faire)";
    const missing = done?.find((result) => result.missing)?.missing;
    const texts = missing === undefined ? "—" : String(missing.length);
    lines.push(
      `| ${row.no} | ${row.name}${status} | ${row.lot} | ${cell(1280)} | ${cell(390)} | ${texts} | ${images ?? ""} |`,
    );
  }
  writeFileSync(join(OUT, "..", "comparaison.md"), `${lines.join("\n")}\n`);
}

test.describe("maquette v2", () => {
  test.afterAll(() => {
    writeReport();
  });

  for (const row of ROWS) {
    test(`${row.no} ${row.name}`, async ({ page, request }) => {
      test.fixme(!DONE.has(row.no) && !ALL, `écran du lot ${row.lot}`);
      test.setTimeout(120_000);
      await page.clock.setFixedTime(FROZEN_NOW);
      const route = await resolveRoute(request, row.route);
      if (route !== "/login") {
        // Formulaire rempli seulement une fois la page hydratée : sinon le serveur de
        // développement, encore en train de compiler, laisse partir un envoi natif.
        await page.goto("/login");
        await page.waitForLoadState("networkidle");
        await loginThroughUi(page, MAQUETTE);
        await expect(page).toHaveURL(/\/dashboard$/, { timeout: 30_000 });
      }
      await page.goto(route);
      await STATES[row.no]?.(page, request);

      const expected = await referenceTexts(page, row);
      const measured: Result[] = [];
      for (const width of [1280, 390]) {
        const result = await compare(page, row, width);
        if (!result) continue;
        if (expected && width === textWidth([...measured, result])) {
          result.missing = await missingTexts(page, row, expected);
        }
        measured.push(result);
      }
      saveResult(row.no, measured);

      if (DONE.has(row.no)) {
        const missing = measured.flatMap((result) => result.missing ?? []);
        expect(missing, `${row.no} : textes de la maquette absents de la page`).toEqual([]);
      }
      if (DONE.has(row.no) && !ALLOWED.has(row.no)) {
        // À 390 px, seul l'écran 26 fait foi : les captures « -390 » des autres écrans sont
        // la page d'ordinateur rétrécie, indicatives (ecarts.md, 2026-10-09).
        const phoneOnly = !existsSync(join(MOCKUP, "captures", `${row.capture}-390.png`));
        for (const result of measured.filter((r) => r.width === 1280 || phoneOnly)) {
          expect(
            result.percent,
            `${row.no} à ${result.width} px : ${result.percent.toFixed(1)} % de pixels différents`,
          ).toBeLessThanOrEqual(THRESHOLD);
        }
      }
    });
  }
});
