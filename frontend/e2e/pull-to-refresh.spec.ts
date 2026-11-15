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

  test("installed app: a pull with the menu open does not reload", async () => {
    await app.page.goto("/");
    await app.page.getByRole("button", { name: "Menu", exact: true }).click();
    await expect(app.page.getByRole("dialog", { name: "Menu" })).toBeVisible();
    await mark(app.page);
    // On the heading of the sheet: a touch on the dim area would only close the menu (and its target is gone, so the
    // rest of the gesture never reaches the page); here the touch stays inside the dialog and only the guard stops it.
    const heading = (await app.page.getByRole("dialog", { name: "Menu" }).getByRole("heading", { name: "Menu" }).boundingBox())!;
    await drag(app.cdp, heading.x + heading.width / 2, heading.y + heading.height / 2, 200);
    await app.page.waitForTimeout(800);
    expect(await markerSurvives(app.page)).toBe(true);
    await app.page.keyboard.press("Escape");
  });

  test("installed app: a pull while a write is in flight does not reload", async () => {
    await app.page.goto("/sheets/L4736-0001");
    // Hold the write on its way: it is still pending when the finger lets go. It never reaches the hub.
    let release: () => void = () => {};
    const held = new Promise<void>((resolve) => (release = resolve));
    await app.page.route("**/api/v1/**", async (route) => {
      if (route.request().method() === "GET") return route.continue();
      await held;
      await route.abort().catch(() => {}); // the test may be over by now
    });
    await app.page.getByRole("button", { name: "Mark cells as used" }).click();
    await app.page.getByRole("gridcell", { name: /^Cell 48,/ }).click();
    await app.page.getByRole("textbox", { name: /^Purpose/ }).fill("e2e pull probe");
    await app.page.getByRole("button", { name: "Mark 1 cell as used" }).click();
    await expect(app.page.locator('[role="dialog"], [role="alertdialog"]')).toHaveCount(0); // so the dialog guard is not what holds it
    // Marking a cell scrolled the page down; the pull must start at the top, so that only the pending write can stop it.
    await app.page.evaluate(() => window.scrollTo(0, 0));
    await expect.poll(() => app.page.evaluate(() => window.scrollY)).toBe(0);
    await mark(app.page);
    await drag(app.cdp, 195, 30, 200);
    await app.page.waitForTimeout(800);
    expect(await markerSurvives(app.page)).toBe(true);
    release();
    await app.page.unrouteAll({ behavior: "ignoreErrors" });
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
