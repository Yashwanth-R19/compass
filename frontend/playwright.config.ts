import { defineConfig, devices } from "@playwright/test";

// One Playwright test, not a suite (RULES.md sec 8, Part H) -- this config
// exists only to run e2e/onboard-flow.spec.ts against a real dev server
// with the backend fully mocked via page.route(), never a live API.
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: "list",
  // The default 30s budget stopped being enough once session 11 extended
  // this single flow with Audit mode (a second full page load plus more
  // graph rendering) -- still one test, not a suite, just a longer one.
  timeout: 60_000,
  use: {
    baseURL: "http://localhost:5173",
    trace: "retain-on-failure",
  },
  webServer: {
    command: "npm run dev -- --port 5173 --strictPort",
    url: "http://localhost:5173",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
