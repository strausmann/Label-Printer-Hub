import { resolve } from "node:path";

/** Two throw-away hubs: one with an admin key, one waiting for its first admin key (D7). */
export const MAIN = {
  port: 8765,
  url: "http://localhost:8765",
  keyFile: resolve(import.meta.dirname, ".tmp", "main.key"),
};
export const BOOTSTRAP = {
  port: 8766,
  url: "http://localhost:8766",
  keyFile: resolve(import.meta.dirname, ".tmp", "bootstrap.key"),
};

/** Pictures for the fake camera of the scan tests (written by `global-setup.ts`). */
export const FAKE_CAMERA = {
  qr: resolve(import.meta.dirname, ".tmp", "camera-qr.y4m"),
  dataMatrix: resolve(import.meta.dirname, ".tmp", "camera-data-matrix.y4m"),
  sheet: resolve(import.meta.dirname, ".tmp", "camera-sheet.y4m"),
  qrText: "https://hub.example.invalid/asset/42",
  dataMatrixText: "https://hub.example.invalid/spool/5",
  /** The sheet ID cell of the first seeded L4736REV sheet, as the scanner reads it. */
  sheetText: "sheet:L4736-0001",
};

/** The throw-away hub the README screenshots are taken from (`playwright.screenshots.config.ts`). */
export const SHOTS = {
  port: 8795,
  url: "http://localhost:8795",
  keyFile: resolve(import.meta.dirname, ".tmp", "shots.key"),
};

/** The instant every seeded job and sheet is stamped with (`E2E_FIXTURE_TIME` of `backend/tests/e2e_app.py`). */
export const FIXTURE_TIME = "2026-11-01T08:00:00Z";
