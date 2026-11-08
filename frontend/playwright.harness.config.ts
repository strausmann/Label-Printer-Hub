import { defineConfig, devices } from "@playwright/test";

// Real-browser layout checks of components that no route renders yet (jsdom has no layout engine).
// `pnpm exec playwright test -c playwright.harness.config.ts`; the page is harness/*.html on the vite dev server.
export const HARNESS_URL = "http://127.0.0.1:5199";

export default defineConfig({
  testDir: "./harness",
  testMatch: "**/*.spec.ts",
  workers: 1,
  reporter: "list",
  use: { baseURL: HARNESS_URL },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: { command: "pnpm exec vite --host 127.0.0.1 --port 5199 --strictPort", url: `${HARNESS_URL}/harness/sheet-grid.html`, reuseExistingServer: false, timeout: 120_000 },
});
