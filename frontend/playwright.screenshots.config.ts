import { defineConfig } from "@playwright/test";
import { FIXTURE_TIME, SHOTS } from "./e2e/env";

// Renders the README screenshots against the real hub on the e2e fixtures (`backend/tests/e2e_app.py`).
// Run by `pnpm screenshots`; the regular e2e config ignores the spec.
const python = "${E2E_PYTHON:-.venv/bin/python}";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "readme-screenshots.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: "list",
  use: { baseURL: SHOTS.url },
  projects: [
    {
      name: "screenshots",
      use: {
        browserName: "chromium",
        // Text is rasterised the same way on every run: grayscale (no LCD sub-pixels, whose use depends on layer timing), no hinting.
        launchOptions: { args: ["--disable-lcd-text", "--font-render-hinting=none", "--disable-gpu", "--num-raster-threads=1", "--force-color-profile=srgb", "--disable-gpu-compositing", "--disable-gpu-rasterization", "--disable-partial-raster"] },
      },
    },
  ],
  webServer: {
    command:
      `pnpm build && cd ../backend && E2E_FIXTURE_TIME=${FIXTURE_TIME} E2E_PORT=${SHOTS.port} E2E_KEY_FILE=${SHOTS.keyFile} ` +
      `PRINTER_HUB_WEB_DIST_DIR=../frontend/dist ${python} -m uvicorn tests.e2e_app:app --port ${SHOTS.port}`,
    url: `${SHOTS.url}/healthz`,
    reuseExistingServer: false,
    timeout: 240_000,
  },
});
