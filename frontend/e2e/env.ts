// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { resolve } from "node:path";

/** The port named by an environment variable, or its default; a value that is no port fails the config. */
function portFrom(name: string, fallback: number): number {
  const raw = process.env[name];
  if (raw === undefined || raw === "") return fallback;
  const port = Number(raw);
  if (!/^\d+$/.test(raw) || !Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error(`${name} must be a port number (1-65535), got "${raw}"`);
  }
  return port;
}

const MAIN_PORT = portFrom("LABELYARD_E2E_MAIN_PORT", 8765);
const BOOTSTRAP_PORT = portFrom("LABELYARD_E2E_BOOTSTRAP_PORT", 8766);
const SHOTS_PORT = portFrom("LABELYARD_E2E_SHOTS_PORT", 8795);

/** Two throw-away hubs: one with an admin key, one waiting for its first admin key (D7). */
export const MAIN = {
  port: MAIN_PORT,
  url: `http://localhost:${MAIN_PORT}`,
  keyFile: resolve(import.meta.dirname, ".tmp", "main.key"),
};
export const BOOTSTRAP = {
  port: BOOTSTRAP_PORT,
  url: `http://localhost:${BOOTSTRAP_PORT}`,
  keyFile: resolve(import.meta.dirname, ".tmp", "bootstrap.key"),
};

/** Pictures for the fake camera of the scan tests (written by `global-setup.ts`). */
export const FAKE_CAMERA = {
  qr: resolve(import.meta.dirname, ".tmp", "camera-qr.y4m"),
  dataMatrix: resolve(import.meta.dirname, ".tmp", "camera-data-matrix.y4m"),
  sheet: resolve(import.meta.dirname, ".tmp", "camera-sheet.y4m"),
  grocycode: resolve(import.meta.dirname, ".tmp", "camera-grocycode.y4m"),
  grocyBattery: resolve(import.meta.dirname, ".tmp", "camera-grocy-battery.y4m"),
  /** The item label for 60 frames, then the sheet code (`qrText`, `sheetText`), looping. */
  itemThenSheet: resolve(import.meta.dirname, ".tmp", "camera-item-then-sheet.y4m"),
  qrText: "https://hub.example.invalid/asset/42",
  dataMatrixText: "https://hub.example.invalid/spool/5",
  /** The sheet ID cell of the first seeded L4736REV sheet, as the scanner reads it. */
  sheetText: "sheet:L4736-0001",
  /** A Grocy product label, as Grocy prints it. */
  grocycodeText: "grcy:p:13",
  /** A Grocy battery label; the e2e hub's Grocy fake knows battery 4. */
  grocyBatteryText: "grcy:b:4",
};

/** The throw-away hub the README screenshots are taken from (`playwright.screenshots.config.ts`). */
export const SHOTS = {
  port: SHOTS_PORT,
  url: `http://localhost:${SHOTS_PORT}`,
  keyFile: resolve(import.meta.dirname, ".tmp", "shots.key"),
};

/** The instant every seeded job and sheet is stamped with (`E2E_FIXTURE_TIME` of `backend/tests/e2e_app.py`). */
export const FIXTURE_TIME = "2026-11-01T08:00:00Z";
