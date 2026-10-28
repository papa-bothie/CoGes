import { defineConfig, devices } from "@playwright/test";

/**
 * Application installable (prompt 29, P2, ADR 0102) : le service worker ne s'enregistre
 * qu'en production. `make front-pwa-e2e` : l'API des parcours (:8100) et un **build de
 * production** du front (`e2e.sh front-prod`, :3102), sur la base `coges_e2e`.
 */
const PWA_FRONT = "http://localhost:3102";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "pwa.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: PWA_FRONT,
    locale: "fr-FR",
    timezoneId: "Africa/Dakar",
    trace: "retain-on-failure",
    serviceWorkers: "allow",
  },
  webServer: [
    {
      command: "../deploy/scripts/e2e.sh api",
      url: "http://localhost:8100/api/v1/health",
      reuseExistingServer: true,
      timeout: 120_000,
    },
    {
      command: "../deploy/scripts/e2e.sh front-prod",
      url: `${PWA_FRONT}/login`,
      reuseExistingServer: true,
      timeout: 600_000,
    },
  ],
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 900 } },
    },
  ],
});
