import { defineConfig, devices } from "@playwright/test";

/**
 * Parcours de bout en bout contre une API **réelle**, sur une base **dédiée** `coges_e2e`
 * (ADR 0059) : jamais `coges`, la préproduction ni Neon.
 *
 * `make front-e2e` recrée la base (`make e2e-reset` : migrations puis seed-demo), puis
 * Playwright démarre l'API e2e (:8100, débit non limité) et le front e2e (:3100, build
 * séparé) s'ils ne tournent pas déjà. Le développement (:8001 / :3000) n'est pas touché.
 * `E2E_BASE_URL` vise un front déjà déployé (préversion) : aucun serveur n'est alors lancé.
 */
const E2E_FRONT = "http://localhost:3100";

export default defineConfig({
  testDir: "./e2e",
  // La comparaison à la maquette a ses propres serveurs, à l'heure figée.
  testIgnore: "maquette.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? E2E_FRONT,
    locale: "fr-FR",
    timezoneId: "Africa/Dakar",
    trace: "retain-on-failure",
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
          command: "../deploy/scripts/e2e.sh front",
          url: `${E2E_FRONT}/login`,
          reuseExistingServer: true,
          timeout: 180_000,
        },
      ],
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } },
    },
  ],
});
