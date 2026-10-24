/**
 * Accessibilité Lighthouse de l'administration (prompt 27, D6) : la connexion et le tableau
 * de bord, en clair, seuil 95.
 *
 * `make admin-lighthouse` : serveurs des parcours e2e (API :8100, administration :3200),
 * lancés s'ils ne répondent pas, puis arrêtés. Chromium de Playwright, profil gardé entre
 * les pages : la session de l'administrateur suit Lighthouse.
 *
 * Écrit `docs/design/captures/admin/apres/lighthouse.md` et échoue sous 95.
 */
import { spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "@playwright/test";
import lighthouse from "lighthouse";
import desktopConfig from "lighthouse/core/config/desktop-config.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const ADMIN_URL = "http://localhost:3200";
const API = "http://localhost:8100/api/v1";
const PORT = 9334;
const THRESHOLD = 95;
const OUT = join(HERE, "..", "..", "docs", "design", "captures", "admin", "apres");
const ADMIN = { email: "admin@e2e.example.com", password: "admin-coges-e2e-2026" };
const SCREENS = [
  ["Connexion", "/login"],
  ["Tableau de bord", "/"],
];

async function up(url) {
  try {
    return (await fetch(url)).ok;
  } catch {
    return false;
  }
}

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

const servers = [await ensure("api", `${API}/health`), await ensure("admin", `${ADMIN_URL}/login`)];
const profile = mkdtempSync(join(tmpdir(), "coges-admin-lighthouse-"));
const context = await chromium.launchPersistentContext(profile, {
  args: [`--remote-debugging-port=${PORT}`],
  locale: "fr-FR",
  timezoneId: "Africa/Dakar",
});
const rows = [];
try {
  const page = context.pages()[0] ?? (await context.newPage());
  for (const [name, path] of SCREENS) {
    if (path === "/") {
      await page.goto(`${ADMIN_URL}/login`);
      await page.waitForLoadState("networkidle");
      await page.getByLabel("E-mail").fill(ADMIN.email);
      await page.getByLabel("Mot de passe").fill(ADMIN.password);
      await page.getByRole("button", { name: "Se connecter" }).click();
      await page.getByRole("heading", { name: "Tableau de bord" }).waitFor({ timeout: 60_000 });
    }
    const result = await lighthouse(
      `${ADMIN_URL}${path}`,
      {
        port: PORT,
        onlyCategories: ["accessibility"],
        disableStorageReset: true,
        logLevel: "error",
      },
      desktopConfig,
    );
    const landed = new URL(result.lhr.finalDisplayedUrl).pathname;
    if (landed !== path) throw new Error(`${path} a mené à ${landed}`);
    const category = result.lhr.categories.accessibility;
    const failed = Object.values(result.lhr.audits)
      .filter((audit) => category.auditRefs.some((ref) => ref.id === audit.id && ref.weight > 0))
      .filter((audit) => audit.score !== null && audit.score < 1)
      .map((audit) => audit.id);
    const score = Math.round(category.score * 100);
    rows.push({ name, path, score, failed });
    console.log(
      `${String(score).padStart(3)}  ${name}${failed.length ? `  (${failed.join(", ")})` : ""}`,
    );
  }
} finally {
  await context.close();
  rmSync(profile, { recursive: true, force: true });
  for (const child of servers) if (child?.pid) process.kill(-child.pid, "SIGTERM");
}

const below = rows.filter((row) => row.score < THRESHOLD);
mkdirSync(OUT, { recursive: true });
writeFileSync(
  join(OUT, "lighthouse.md"),
  [
    "# Lighthouse — accessibilité de l'administration",
    "",
    `Mesuré par \`make admin-lighthouse\` (Lighthouse 13.5.0, Chromium de Playwright, base \`coges_e2e\`, thème clair). Seuil : ${THRESHOLD}.`,
    "",
    "| Écran | Page | Score | Audits non réussis |",
    "|---|---|---|---|",
    ...rows.map(
      (row) =>
        `| ${row.name} | \`${row.path}\` | ${row.score} | ${row.failed.map((id) => `\`${id}\``).join(", ") || "—"} |`,
    ),
    "",
    below.length === 0
      ? `Les deux écrans atteignent ${THRESHOLD} ou plus.`
      : `Sous ${THRESHOLD} : ${below.map((row) => row.name).join(", ")}.`,
    "",
  ].join("\n"),
);
console.log(`\nRapport : ${join(OUT, "lighthouse.md")}`);
process.exit(below.length === 0 ? 0 : 1);
