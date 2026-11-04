import { defineConfig, devices } from "@playwright/test";
import { BOOTSTRAP, MAIN } from "./e2e/env";

// The hub under test is the real backend serving the production build (D1) on a temp
// database with mock printers: `backend/tests/e2e_app.py`. `E2E_PYTHON` overrides the
// interpreter (CI uses the one on PATH, locally the backend venv).
const python = "${E2E_PYTHON:-.venv/bin/python}";
const serve = (port: number, keyFile: string, extra = "") =>
  `cd ../backend && ${extra}E2E_PORT=${port} E2E_KEY_FILE=${keyFile} ` +
  `PRINTER_HUB_WEB_DIST_DIR=../frontend/dist ${python} -m uvicorn tests.e2e_app:app --port ${port}`;

export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/*.spec.ts",
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: { baseURL: MAIN.url, trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `pnpm build && ${serve(MAIN.port, MAIN.keyFile)}`,
      url: `${MAIN.url}/healthz`,
      reuseExistingServer: false,
      timeout: 240_000,
    },
    {
      // Starts once the first hub is up, i.e. after the build it waits for has finished.
      command:
        `until curl -sf ${MAIN.url}/healthz >/dev/null; do sleep 1; done; ` +
        serve(BOOTSTRAP.port, BOOTSTRAP.keyFile, "E2E_BOOTSTRAP=1 "),
      url: `${BOOTSTRAP.url}/healthz`,
      reuseExistingServer: false,
      timeout: 240_000,
    },
  ],
});
