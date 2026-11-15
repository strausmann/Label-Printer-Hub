// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

// Turns the website screenshots (lossless PNGs written by e2e/readme-screenshots.spec.ts into
// e2e/.tmp/site-shots/) into WebP files in website/src/assets/screens/, named
// <shot>.<en|de>.<light|dark>.webp, and fails when one is over budget. The encoder is the WebP
// encoder of the Chromium that Playwright already installs, so the step needs no image library.
// Run by `pnpm screenshots` after the screenshots were taken.
import { mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = import.meta.dirname;
export const SOURCE = resolve(HERE, "..", "e2e", ".tmp", "site-shots");
export const TARGET = resolve(HERE, "..", "..", "website", "src", "assets", "screens");
export const QUALITY = 0.86;
export const BUDGET_BYTES = 200 * 1024;

const SHOT = /^(?<shot>[a-z0-9-]+)\.(?<lang>en|de)\.(?<theme>light|dark)\.png$/;

/** The WebP file name for a website PNG, or null when the name is not a website shot. */
export function webpName(png) {
  const match = SHOT.exec(png);
  return match ? png.replace(/\.png$/, ".webp") : null;
}

/** The website PNGs of a directory with their WebP names, sorted; other files are ignored. */
export function plan(names) {
  return names
    .map((png) => ({ png, webp: webpName(png) }))
    .filter((entry) => entry.webp !== null)
    .sort((a, b) => a.png.localeCompare(b.png));
}

/** The WebP files over the byte budget, as `{ name, size }`. */
export function overBudget(files, budget = BUDGET_BYTES) {
  return files.filter((file) => file.size > budget);
}

async function encode(page, png) {
  const dataUrl = await page.evaluate(
    async ({ base64, quality }) => {
      const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
      const bitmap = await createImageBitmap(new Blob([bytes], { type: "image/png" }));
      const canvas = document.createElement("canvas");
      canvas.width = bitmap.width;
      canvas.height = bitmap.height;
      canvas.getContext("2d").drawImage(bitmap, 0, 0);
      return canvas.toDataURL("image/webp", quality);
    },
    { base64: png.toString("base64"), quality: QUALITY },
  );
  if (!dataUrl.startsWith("data:image/webp;base64,")) throw new Error("the browser did not encode WebP");
  return Buffer.from(dataUrl.slice("data:image/webp;base64,".length), "base64");
}

async function main() {
  const entries = plan(readdirSync(SOURCE));
  if (entries.length === 0) {
    console.error(`No website screenshots in ${SOURCE}`);
    process.exit(1);
  }
  const { chromium } = await import("@playwright/test");
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    mkdirSync(TARGET, { recursive: true });
    for (const { png, webp } of entries) {
      writeFileSync(resolve(TARGET, webp), await encode(page, readFileSync(resolve(SOURCE, png))));
    }
  } finally {
    await browser.close();
  }
  const written = entries.map(({ webp }) => ({ name: webp, size: statSync(resolve(TARGET, webp)).size }));
  const over = overBudget(written);
  for (const file of over) console.error(`${file.name} is ${file.size} bytes, over the ${BUDGET_BYTES} byte budget`);
  if (over.length > 0) process.exit(1);
  console.log(`${written.length} website screenshots written to ${TARGET}, all within ${BUDGET_BYTES / 1024} KB.`);
}

if (process.argv[1] === fileURLToPath(import.meta.url)) await main();
