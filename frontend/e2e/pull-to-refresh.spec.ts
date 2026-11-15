// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import type { Browser, BrowserContext, CDPSession, Page } from "@playwright/test";
import { MAIN } from "./env";
import { expect, mainKey, signInWith, test } from "./fixtures";

// #331: pull down at the top to reload. The installed app has no browser reload, so it brings its own gesture; a
// browser tab keeps the browser's. Touches go through the DevTools protocol, which is the only way to give a page
// real touch events; "installed" is a matchMedia answer, since headless Chromium cannot be installed.

const PHONE = { viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true } as const;

async function open(browser: Browser, standalone: boolean) {
  const context: BrowserContext = await browser.newContext({ baseURL: MAIN.url, ...PHONE });
  if (standalone) {
    await context.addInitScript(() => {
      const real = window.matchMedia.bind(window);
      window.matchMedia = (query: string) =>
        query === "(display-mode: standalone)"
          ? ({ matches: true, media: query, onchange: null, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent: () => false } as MediaQueryList)
          : real(query);
    });
  }
  const page = await context.newPage();
  await page.goto("/");
  await signInWith(page, mainKey());
  await expect(page.getByRole("navigation", { name: /^(Main|Tabs)$/ }).first()).toBeVisible();
  const cdp = await context.newCDPSession(page);
  return { context, page, cdp };
}

/** One finger down at (x, y), then straight down by `dy` in steps, then up. */
async function drag(cdp: CDPSession, x: number, y: number, dy: number) {
  await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x, y }] });
  for (let travelled = 10; travelled <= dy; travelled += 10) {
    await cdp.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ x, y: y + travelled }] });
  }
  await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
}

const mark = (page: Page) => page.evaluate(() => ((window as unknown as { __marker?: number }).__marker = 1));
/** True while the page from before is still there (a reload drops every window property). */
const markerSurvives = (page: Page) =>
  page.evaluate(() => (window as unknown as { __marker?: number }).__marker === 1).catch(() => false);

test.describe.serial("pull to refresh", () => {
  let tab: Awaited<ReturnType<typeof open>>;
  let app: Awaited<ReturnType<typeof open>>;
  test.beforeAll(async ({ browser }) => {
    tab = await open(browser, false);
    app = await open(browser, true);
  });
  test.afterAll(async () => {
    await tab.context.close();
    await app.context.close();
  });

  test("the root no longer locks vertical overscroll", async () => {
    const style = await tab.page.evaluate(() => {
      const css = getComputedStyle(document.documentElement);
      return { x: css.overscrollBehaviorX, y: css.overscrollBehaviorY, standalone: document.documentElement.hasAttribute("data-standalone") };
    });
    expect(style).toEqual({ x: "none", y: "auto", standalone: false });
    const installed = await app.page.evaluate(() => getComputedStyle(document.documentElement).overscrollBehaviorY);
    expect(installed).toBe("none");
  });

  test("installed app: a pull from the top past the threshold reloads", async () => {
    await app.page.goto("/");
    await mark(app.page);
    await drag(app.cdp, 195, 200, 200);
    await expect.poll(() => markerSurvives(app.page), { timeout: 10_000 }).toBe(false);
    await expect(app.page.getByRole("navigation", { name: /^(Main|Tabs)$/ }).first()).toBeVisible();
  });

  test("installed app: a short pull does not reload", async () => {
    await app.page.goto("/");
    await mark(app.page);
    await drag(app.cdp, 195, 200, 100);
    await app.page.waitForTimeout(800);
    expect(await markerSurvives(app.page)).toBe(true);
    await expect(app.page.getByTestId("pull-indicator")).toHaveCSS("opacity", "0");
  });

  test("installed app: a pull inside the scrolling sheet grid does not reload", async () => {
    await app.page.goto("/sheets/L4736-0001");
    await app.page.getByRole("button", { name: "Mark cells as used" }).click();
    const grid = app.page.locator('[data-scroll="both"]');
    await expect(grid).toBeVisible();
    // The grid really scrolls (otherwise the test would pass for the wrong reason).
    expect(await grid.evaluate((el) => el.scrollWidth > el.clientWidth)).toBe(true);
    expect(await app.page.evaluate(() => window.scrollY)).toBe(0);
    const box = (await grid.boundingBox())!;
    await mark(app.page);
    await drag(app.cdp, box.x + box.width / 2, box.y + 40, 200);
    await app.page.waitForTimeout(800);
    expect(await markerSurvives(app.page)).toBe(true);
  });

  test("browser tab: the own gesture is off", async () => {
    await tab.page.goto("/");
    await mark(tab.page);
    await drag(tab.cdp, 195, 200, 200);
    await tab.page.waitForTimeout(800);
    expect(await markerSurvives(tab.page)).toBe(true);
    await expect(tab.page.getByTestId("pull-indicator")).toHaveCount(0);
  });
});
