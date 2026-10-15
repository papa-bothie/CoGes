/**
 * Accessibilité Lighthouse des 26 écrans de la maquette v2 (phase 15, ADR 0075).
 *
 * `make lighthouse` : mêmes données et mêmes serveurs que `make maquette-check` (entreprise
 * `maquette` de `coges_e2e`, API :8101 à l'heure figée, front :3101). Les serveurs sont
 * lancés s'ils ne répondent pas, puis arrêtés. Chromium de Playwright, profil gardé entre
 * les pages : la session de la gérante (cookie de rafraîchissement) suit Lighthouse.
 *
 * Écrit `docs/design/captures/phase-15/lighthouse.md` et échoue sous 95.
 */
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "@playwright/test";
import lighthouse from "lighthouse";
import desktopConfig from "lighthouse/core/config/desktop-config.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const FRONT = "http://localhost:3101";
const API = "http://localhost:8101/api/v1";
const PORT = 9333;
const THRESHOLD = 95;
const REPORT = join(HERE, "..", "..", "docs", "design", "captures", "phase-15", "lighthouse.md");
const MAQUETTE = {
  slug: "maquette",
  email: "gerant@maquette.example.com",
  password: "demo-coges-2026",
};

/** Les 26 écrans (`docs/design/maquette-v2/ecrans.md`), puis les rubriques des réglages. */
const SCREENS = [
  ["25", "Connexion", "/login"],
  ["01", "Accueil", "/dashboard"],
  ["02", "Nouvelle vente", "/sales/new"],
  ["03", "Liste des ventes", "/sales"],
  ["04", "Détail d'une vente", "/sales/{sale}"],
  ["05", "Reçu", "/sales/{sale}/receipt"],
  ["06", "Retour d'articles", "/sales/{sale}/returns/new"],
  ["07", "Liste des articles", "/products"],
  ["08", "Fiche article", "/products/{product}"],
  ["09", "Nouvel article", "/products/new"],
  ["10", "Corriger le stock", "/inventory/adjust"],
  ["11", "Recevoir une livraison", "/inventory/receive"],
  ["12", "Rayons", "/products/categories"],
  ["13", "Clients et fournisseurs", "/customers"],
  ["14", "Fiche client", "/customers/{customer}"],
  ["15", "Ajouter une personne", "/customers/new"],
  ["16", "Fiche fournisseur", "/suppliers/{supplier}"],
  ["17", "L'argent", "/finance"],
  ["18", "Encaisser une dette", "/finance/collect"],
  ["19", "Payer un fournisseur", "/finance/pay"],
  ["20", "Dépenses", "/finance/expenses"],
  ["21", "Entrées et sorties", "/finance/cash"],
  ["22", "Conseils", "/insights"],
  ["23", "Alertes", "/notifications"],
  ["24", "Réglages : ma boutique", "/settings"],
  ["24b", "Réglages : personnes", "/settings/people"],
  ["24c", "Réglages : qui peut faire quoi", "/settings/rights"],
  ["24d", "Réglages : historique", "/settings/history"],
  ["24e", "Réglages : fichiers Excel", "/settings/files"],
  ["26", "Sur téléphone (accueil, 390 px)", "/dashboard"],
];

async function up(url) {
  try {
    return (await fetch(url)).ok;
  } catch {
    return false;
  }
}

/** Lance un serveur de `e2e.sh` s'il ne répond pas encore ; rend de quoi l'arrêter. */
async function ensure(command, url) {
  if (await up(url)) return null;
  const child = spawn(join(HERE, "..", "..", "deploy", "scripts", "e2e.sh"), [command], {
    cwd: join(HERE, ".."),
    stdio: "ignore",
    detached: true,
  });
  for (let waited = 0; waited < 240; waited += 2) {
    if (await up(url)) return child;
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
  throw new Error(`${command} ne répond pas sur ${url}`);
}

async function ids() {
  const login = await fetch(`${API}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      company_slug: MAQUETTE.slug,
      email: MAQUETTE.email,
      password: MAQUETTE.password,
    }),
  });
  const { access_token: token } = await login.json();
  const first = async (path) => {
    const response = await fetch(`${API}${path}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    return (await response.json()).items[0].id;
  };
  return {
    sale: await first("/sales?search=V-001044&page_size=1"),
    product: await first("/products?search=Riz&page_size=1"),
    customer: await first("/customers?search=Moussa&page_size=1"),
    supplier: await first("/suppliers?search=Sandaga&page_size=1"),
  };
}

const servers = [
  await ensure("maquette-api", `${API}/health`),
  await ensure("maquette-front", `${FRONT}/login`),
];
const profile = mkdtempSync(join(tmpdir(), "coges-lighthouse-"));
const context = await chromium.launchPersistentContext(profile, {
  args: [`--remote-debugging-port=${PORT}`],
  locale: "fr-FR",
  timezoneId: "Africa/Dakar",
});
const rows = [];
try {
  const found = await ids();
  const page = context.pages()[0] ?? (await context.newPage());
  for (const [no, name, template] of SCREENS) {
    if (no === "01") {
      // Connexion faite une fois, après la mesure de l'écran de connexion lui-même.
      await page.goto(`${FRONT}/login`);
      await page.waitForLoadState("networkidle");
      await page.getByLabel("Code de la boutique").fill(MAQUETTE.slug);
      await page.getByLabel("Votre e-mail ou téléphone").fill(MAQUETTE.email);
      await page.getByLabel("Mot de passe", { exact: true }).fill(MAQUETTE.password);
      await page.getByRole("button", { name: "Entrer" }).click();
      await page.waitForURL(/\/dashboard$/, { timeout: 60_000 });
    }
    const path = template.replace(/\{(\w+)\}/g, (_, key) => found[key]);
    const phone = no === "26";
    const result = await lighthouse(
      `${FRONT}${path}`,
      {
        port: PORT,
        onlyCategories: ["accessibility"],
        disableStorageReset: true,
        logLevel: "error",
        ...(phone
          ? {
              formFactor: "mobile",
              screenEmulation: {
                mobile: true,
                width: 390,
                height: 844,
                deviceScaleFactor: 2,
                disabled: false,
              },
            }
          : {}),
      },
      phone ? undefined : desktopConfig,
    );
    // Une page redirigée (session perdue → connexion) mesurerait le mauvais écran.
    const landed = new URL(result.lhr.finalDisplayedUrl).pathname;
    // « Nouvelle vente » reprend le brouillon du jour (ADR 0070) : `/sales/<id>/edit`.
    const expected = no === "02" ? /^\/sales\/[^/]+\/edit$/ : null;
    if (landed !== path && !expected?.test(landed))
      throw new Error(`${no} : ${path} a mené à ${landed}`);
    const category = result.lhr.categories.accessibility;
    const failed = Object.values(result.lhr.audits)
      .filter((audit) => category.auditRefs.some((ref) => ref.id === audit.id && ref.weight > 0))
      .filter((audit) => audit.score !== null && audit.score < 1)
      .map((audit) => audit.id);
    const score = Math.round(category.score * 100);
    rows.push({ no, name, path: template, score, failed });
    console.log(
      `${no.padEnd(3)} ${String(score).padStart(3)}  ${name}${failed.length ? `  (${failed.join(", ")})` : ""}`,
    );
  }
} finally {
  await context.close();
  rmSync(profile, { recursive: true, force: true });
  for (const child of servers) if (child?.pid) process.kill(-child.pid, "SIGTERM");
}

const below = rows.filter((row) => row.score < THRESHOLD);
writeFileSync(
  REPORT,
  [
    "# Lighthouse — accessibilité des écrans de la maquette v2",
    "",
    `Mesuré par \`make lighthouse\` (Lighthouse 13.5.0, Chromium de Playwright, entreprise \`maquette\`, thème clair ; 390 px pour l'écran 26). Seuil : ${THRESHOLD}.`,
    "",
    "| Écran | Page | Score | Audits non réussis |",
    "|---|---|---|---|",
    ...rows.map(
      (row) =>
        `| ${row.no} ${row.name} | \`${row.path}\` | ${row.score} | ${row.failed.map((id) => `\`${id}\``).join(", ") || "—"} |`,
    ),
    "",
    below.length === 0
      ? `Tous les écrans atteignent ${THRESHOLD} ou plus.`
      : `Sous ${THRESHOLD} : ${below.map((row) => row.no).join(", ")}.`,
    "",
  ].join("\n"),
);
console.log(`\nRapport : ${REPORT}`);
process.exit(below.length === 0 ? 0 : 1);
