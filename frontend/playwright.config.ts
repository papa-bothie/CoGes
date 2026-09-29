import { defineConfig, devices } from "@playwright/test";

/**
 * Parcours de bout en bout contre une API **réelle** (locale ou préproduction).
 * Prérequis locaux : `make up && make migrate && make seed-demo && make api`, puis
 * `pnpm dev` (ou `E2E_BASE_URL` vers une préversion déployée).
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    locale: "fr-FR",
    timezoneId: "Africa/Dakar",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } },
    },
  ],
});
