import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";

import { defineConfig, devices } from "@playwright/test";

/**
 * Parcours de l'administration (ADR 0089) contre l'API **réelle** des parcours e2e
 * (`coges_e2e`, :8100, ADR 0059). `make admin-e2e` recrée la base (compte de l'équipe et
 * entreprise `admin-e2e` compris), puis Playwright démarre l'API, le front commerçant
 * (:3100, pour l'accès support) et l'administration (:3200) s'ils ne tournent pas déjà.
 */
const E2E_ADMIN = "http://localhost:3200";

/**
 * Cloudflare Access simulé (ADR 0104) : l'API des parcours exige `Cf-Access-Jwt-Assertion`
 * sur `/api/v1/platform/*`, comme en production. Le jeton est signé par une clé de test
 * (`backend/tests/helpers/access_tokens.py`), dont `e2e.sh api` sert le jeu public ; il
 * part avec chaque requête du navigateur et de `request`, comme le joindrait Cloudflare.
 */
function accessToken(): string {
  const dir = path.resolve(__dirname, "../.e2e-access");
  execFileSync(
    "uv",
    ["run", "--directory", "../backend", "python", "-m", "tests.helpers.access_tokens", dir],
    { cwd: __dirname, stdio: "ignore" },
  );
  return readFileSync(path.join(dir, "token"), "utf-8").trim();
}

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  // Le serveur de développement compile chaque page à sa première visite.
  timeout: 90_000,
  retries: 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? E2E_ADMIN,
    locale: "fr-FR",
    timezoneId: "Africa/Dakar",
    trace: "retain-on-failure",
    extraHTTPHeaders: process.env.E2E_BASE_URL ? {} : { "Cf-Access-Jwt-Assertion": accessToken() },
  },
  webServer: process.env.E2E_BASE_URL
    ? undefined
    : [
        {
          command: "../deploy/scripts/e2e.sh api",
          url: "http://localhost:8100/api/v1/health",
          reuseExistingServer: true,
          timeout: 120_000,
        },
        {
          // Le front commerçant, pour l'accès support (ADR 0092) : « Voir l'entreprise ».
          command: "../deploy/scripts/e2e.sh front",
          url: "http://localhost:3100/login",
          reuseExistingServer: true,
          timeout: 180_000,
        },
        {
          command: "../deploy/scripts/e2e.sh admin",
          url: `${E2E_ADMIN}/login`,
          reuseExistingServer: true,
          timeout: 180_000,
        },
      ],
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } },
    },
  ],
});
