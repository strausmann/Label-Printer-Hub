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
        // Every flag removes a source of pixel differences between two runs, so `pnpm screenshots` renders
        // byte-identical files on the same machine.
        launchOptions: {
          args: [
            // Grayscale text: LCD sub-pixel text is used or not depending on layer timing.
            "--disable-lcd-text",
            // No hinting: glyph outlines are not snapped differently from run to run.
            "--font-render-hinting=none",
            // Software rendering only: GPU paths vary with driver and timing.
            "--disable-gpu",
            "--disable-gpu-compositing",
            "--disable-gpu-rasterization",
            // One raster thread, whole tiles: the order of tile work cannot change the result.
            "--num-raster-threads=1",
            "--disable-partial-raster",
            // The same colour profile everywhere, whatever the host display reports.
            "--force-color-profile=srgb",
          ],
        },
      },
    },
  ],
  webServer: {
    command:
      `pnpm build && cd ../backend && E2E_FIXTURE_TIME=${FIXTURE_TIME} E2E_PORT=${SHOTS.port} E2E_KEY_FILE=${SHOTS.keyFile} ` +
      `LABELYARD_WEB_DIST_DIR=../frontend/dist ${python} -m uvicorn tests.e2e_app:app --port ${SHOTS.port}`,
    url: `${SHOTS.url}/healthz`,
    reuseExistingServer: false,
    timeout: 240_000,
  },
});
