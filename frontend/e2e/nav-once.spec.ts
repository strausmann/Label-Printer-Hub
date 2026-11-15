// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import type { Page } from "@playwright/test";
import { MAIN } from "./env";
import { expect, mainKey, signInWith, test } from "./fixtures";

// #341: on an Android tablet (installed app, landscape) the lower part of the sidebar was drawn again below it while
// the item page of a spool scrolled. The DOM held one sidebar; the sidebar was a sticky box with a scrolling list
// inside it, the pattern Chrome on Android repaints stale. The sidebar is now one fixed box that scrolls as a whole.
const SIDEBAR = ["Overview", "Printers", "Jobs", "Sheets", "Sheet archive", "Calibration", "Snipe-IT", "Grocy", "Spoolman", "Settings"];
const TABS = ["Overview", "Printers", "Scan", "Jobs", "Sheets"];
const PAGES = ["/spool/7", "/", "/printers", "/jobs", "/sheets"];
const SIZES = [
  { name: "phone", width: 390, height: 844 },
  { name: "tablet landscape", width: 1280, height: 800 },
  { name: "small tablet landscape, installed app", width: 1138, height: 690 },
  { name: "desktop", width: 1920, height: 1080 },
];

/** How often each link name appears in the page, visible or not. */
const linkCounts = (page: Page, nav: string) =>
  page.evaluate((label) => {
    const counts: Record<string, number> = {};
    for (const n of document.querySelectorAll(`nav[aria-label="${label}"]`)) {
      for (const a of n.querySelectorAll("a")) {
        const text = (a.textContent ?? "").trim();
        counts[text] = (counts[text] ?? 0) + 1;
      }
    }
    return counts;
  }, nav);

test.describe.serial("each navigation entry is there once (#341)", () => {
  let page: Page;
  test.beforeAll(async ({ browser }) => {
    page = await (await browser.newContext({ baseURL: MAIN.url, hasTouch: true })).newPage();
    await page.goto("/");
    await signInWith(page, mainKey());
    await expect(page.getByRole("navigation", { name: /^(Main|Tabs)$/ }).first()).toBeVisible();
    // The page printer makes the item page long: the sheet preview sits under the label.
    const printers = (await (await page.request.get("/api/v1/printers")).json()) as Array<{ id: string; name: string }>;
    const id = printers.find((p) => p.name === "Office page printer")!.id;
    await page.evaluate((printer) => localStorage.setItem("lph.printer", printer), id);
  });
  test.afterAll(async () => {
    await page.context().close();
  });

  for (const size of SIZES) {
    test(`at ${size.name} width`, async () => {
      await page.setViewportSize({ width: size.width, height: size.height });
      const wide = size.width >= 1024;
      for (const path of PAGES) {
        await page.goto(path);
        await expect(page.getByRole("navigation", { name: wide ? "Main" : "Tabs" })).toBeVisible();
        expect(await page.locator('nav[aria-label="Main"]').count(), path).toBe(1);
        expect(await page.locator('nav[aria-label="Tabs"]').count(), path).toBe(1);
        const sidebar = await linkCounts(page, "Main");
        expect(Object.keys(sidebar).sort(), path).toEqual([...SIDEBAR].sort());
        for (const name of SIDEBAR) expect(sidebar[name], `${path}: ${name}`).toBe(1);
        const tabs = await linkCounts(page, "Tabs");
        for (const name of TABS) expect(tabs[name], `${path}: ${name}`).toBe(1);
        if (!wide) continue;

        // The sidebar is one box that does not move with the page and holds no scroller of its own inside.
        const aside = page.locator("aside", { has: page.locator('nav[aria-label="Main"]') });
        const shape = await aside.evaluate((el) => ({
          position: getComputedStyle(el).position,
          nested: [...el.querySelectorAll("*")].some((c) => ["auto", "scroll"].includes(getComputedStyle(c).overflowY)),
        }));
        expect(shape, path).toEqual({ position: "fixed", nested: false });
        await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
        expect((await aside.boundingBox())!.y, path).toBe(0);
        // Every entry can be reached, on a short screen by scrolling the sidebar itself.
        const settings = page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Settings", exact: true });
        await settings.scrollIntoViewIfNeeded();
        await expect(settings).toBeInViewport({ ratio: 1 });
        await page.evaluate(() => window.scrollTo(0, 0));
      }
    });
  }
});
