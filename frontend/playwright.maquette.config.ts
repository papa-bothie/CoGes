import { defineConfig, devices } from "@playwright/test";

/**
 * Comparaison du front à la maquette v2 (`make maquette-check`, phase 15, ADR 0065).
 *
 * Serveurs à part, pour que les autres parcours gardent l'heure réelle : l'API de la
 * maquette (:8101) a l'heure figée au mardi 6 octobre 2026 à 10 h 45 et le front (:3101)
 * pointe sur elle. Même base `coges_e2e`, entreprise `maquette` (`make e2e-reset`).
 */
const MAQUETTE_FRONT = "http://localhost:3101";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "maquette.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: MAQUETTE_FRONT,
    locale: "fr-FR",
    timezoneId: "Africa/Dakar",
    colorScheme: "light",
  },
  webServer: [
    {
      command: "../deploy/scripts/e2e.sh maquette-api",
      url: "http://localhost:8101/api/v1/health",
      reuseExistingServer: true,
      timeout: 120_000,
    },
    {
      command: "../deploy/scripts/e2e.sh maquette-front",
      url: `${MAQUETTE_FRONT}/login`,
      reuseExistingServer: true,
      timeout: 180_000,
    },
  ],
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
