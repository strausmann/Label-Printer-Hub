// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// Screenshots every mockup: node shoot.mjs [m01 m02 ...]   (run from frontend/ so @playwright/test resolves:
//   cd frontend && node ../docs/designs/1.8.0/src/shoot.mjs m01)
// Screens: 1280 and 390 px wide, light and dark, full page; every view with `kb: true` also at 390x500 (on-screen keyboard open).
// Paper pages (paper: true): light only, 1280 px, plus the first A4 sheet on its own.

import { readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createRequire } from "node:module";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const require = createRequire(join(here, "../../../../frontend/package.json"));
const { chromium } = require("@playwright/test");

const only = process.argv.slice(2);
const files = readdirSync(join(here, "pages")).filter((f) => f.endsWith(".mjs") && (only.length === 0 || only.some((o) => f.startsWith(o))));
const browser = await chromium.launch({ args: ["--font-render-hinting=none", "--force-color-profile=srgb"] });

for (const f of files) {
  const page = (await import(pathToFileURL(join(here, "pages", f)).href)).default;
  const views = page.viewSpecs ?? [{ id: "default" }];
  for (const v of views) {
    const suffix = v.id === "default" ? "" : `-${v.id}`;
    const url = (theme) => `${pathToFileURL(join(root, `${page.file}.html`)).href}?shot&theme=${theme}&view=${v.id}`;
    const sizes = page.paper ? [[1280, 900]] : [[1280, 800], [390, 844]];
    const themes = page.paper ? ["light"] : ["light", "dark"];
    for (const [w, h] of sizes) {
      for (const theme of themes) {
        const ctx = await browser.newContext({ viewport: { width: w, height: h }, colorScheme: theme, deviceScaleFactor: w === 390 ? 2 : 1 });
        const p = await ctx.newPage();
        await p.goto(url(theme));
        await p.evaluate(() => document.fonts.ready);
        await p.screenshot({ path: join(root, "png", `${page.file}${suffix}-${w}-${theme}.png`), fullPage: true });
        if (page.paper && v.id === "default") {
          const el = p.locator(".paper").first();
          if (await el.count()) await el.screenshot({ path: join(root, "png", `${page.file}${suffix}-a4-light.png`) });
        }
        await ctx.close();
      }
    }
    if (v.kb) {
      const ctx = await browser.newContext({ viewport: { width: 390, height: 500 }, colorScheme: "light", deviceScaleFactor: 2 });
      const p = await ctx.newPage();
      await p.goto(url("light").replace("view=" + v.id, "view=" + v.id));
      await p.evaluate(() => { document.documentElement.style.setProperty("--vvh", "500px"); return document.fonts.ready; });
      await p.screenshot({ path: join(root, "png", `${page.file}${suffix}-390x500-light.png`) });
      await ctx.close();
    }
  }
  console.log("shot", page.file);
}
await browser.close();
