import { copyFileSync, existsSync, mkdirSync, rmSync } from "node:fs";
import { resolve } from "node:path";
import type { Page } from "@playwright/test";
import { MAIN } from "./env";
import { expect, mainKey, signInWith, test } from "./fixtures";

const SHOTS = process.env.E2E_SHOTS_DIR;
const shot = async (page: Page, name: string, fullPage = true) => {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: resolve(SHOTS, name), fullPage });
};
const noSideScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);

test("the source link is on the sign-in screen", async ({ page }) => {
  await page.goto("/sign-in");
  const source = page.getByRole("link", { name: "Source code" });
  await expect(source).toBeVisible();
  await expect(source).toHaveAttribute("href", /^https:\/\//);
  await expect(source).toHaveAttribute("rel", /noopener/);
  await shot(page, "about-en-signin.png");
});

// One sign-in for both layouts: the hub limits sign-ins per minute.
test.describe.serial("about", () => {
  let page: Page;
  test.beforeAll(async ({ browser }) => {
    page = await (await browser.newContext({ baseURL: MAIN.url })).newPage();
    await page.goto("/");
    await signInWith(page, mainKey());
    await expect(page.getByRole("navigation", { name: /^(Main|Tabs)$/ }).first()).toBeVisible();
  });
  test.afterAll(async () => {
    await page.context().close();
  });

  test("desktop: the footer link opens the about page", async () => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/");
    await page.getByRole("complementary").getByRole("link", { name: "About and licences" }).click();
    await expect(page).toHaveURL(/\/about$/);
    await expect(page.getByRole("heading", { level: 1, name: "About" })).toBeVisible();
    await expect(page.getByText("AGPL-3.0-or-later").first()).toBeVisible();
    await expect(page.getByRole("main").getByRole("link", { name: "Source code" })).toHaveAttribute("href", /^https:\/\//);
    await shot(page, "about-en-desktop.png");
  });

  test("desktop: the list starts with 50 rows and the rest is one button away", async () => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/about");
    const table = page.getByRole("table");
    await expect(table.getByRole("row")).toHaveCount(51); // header + 50
    await expect(page.getByText(/^50 of \d+ packages$/)).toBeVisible();
    await page.getByRole("button", { name: /^Show all \d+ packages$/ }).click();
    expect(await table.getByRole("row").count()).toBeGreaterThan(250);
    await expect(table.getByRole("row", { name: /^react 19/ })).toBeVisible();
  });

  test("desktop: brother-ql is listed by the filter and its text opens on demand", async () => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/about");
    await page.getByRole("searchbox", { name: "Filter packages" }).fill("brother");
    const table = page.getByRole("table");
    const row = table.getByRole("row", { name: /brother-ql/ });
    await expect(row).toBeVisible();
    await expect(page.getByText("GNU GENERAL PUBLIC LICENSE")).toHaveCount(0);
    await row.getByRole("button", { name: "Show licence text of brother-ql" }).click();
    await expect(page.getByText("GNU GENERAL PUBLIC LICENSE")).toBeVisible();
    await page.getByRole("searchbox", { name: "Filter packages" }).fill("fastapi");
    // A package that ships no text links its licence id to the SPDX text instead.
    await expect(table.getByRole("row", { name: /fastapi/ }).getByRole("link", { name: "MIT: licence text at SPDX" })).toHaveAttribute("href", "https://spdx.org/licenses/MIT.html");
  });

  test("the focus ring of the expand button is not cut off by the table", async () => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/about");
    await page.getByRole("searchbox", { name: "Filter packages" }).fill("brother");
    const button = page.getByRole("button", { name: "Show licence text of brother-ql" });
    await button.focus();
    await page.keyboard.press("Tab");
    await page.keyboard.press("Shift+Tab");
    const clipped = await button.evaluate((el) => {
      const box = el.getBoundingClientRect();
      const outline = parseFloat(getComputedStyle(el).outlineWidth) + parseFloat(getComputedStyle(el).outlineOffset);
      for (let up = el.parentElement; up; up = up.parentElement) {
        if (getComputedStyle(up).overflow !== "visible") {
          const clip = up.getBoundingClientRect();
          // The ring reaches `outline` px past the box (negative offsets pull it inside).
          if (box.right + Math.max(outline, 0) > clip.right || box.bottom + Math.max(outline, 0) > clip.bottom) return up.tagName;
        }
      }
      return null;
    });
    expect(clipped).toBeNull();
  });

  test("desktop: the filter narrows the list", async () => {
    await page.setViewportSize({ width: 1280, height: 500 });
    await page.goto("/about");
    const filter = page.getByRole("searchbox", { name: "Filter packages" });
    await filter.fill("brother");
    await expect(page.getByRole("table").getByRole("row")).toHaveCount(2); // header + brother-ql
    await expect(filter).toBeInViewport();
  });

  test("phone: the top bar link opens the about page", async () => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    await page.getByRole("banner").getByRole("link", { name: "About and licences" }).click();
    await expect(page).toHaveURL(/\/about$/);
    await expect(page.getByRole("heading", { level: 1, name: "About" })).toBeVisible();
    expect(await noSideScroll(page)).toBe(true);
    await shot(page, "about-en-phone.png");
  });

  test("phone: the list stays inside the screen, also with the text open and the keyboard's height", async () => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/about");
    await page.getByRole("searchbox", { name: "Filter packages" }).fill("brother");
    const row = page.getByRole("table").getByRole("row", { name: /brother-ql/ });
    await row.getByRole("button", { name: "Show licence text of brother-ql" }).click();
    await expect(page.getByText("GNU GENERAL PUBLIC LICENSE")).toBeVisible();
    expect(await noSideScroll(page)).toBe(true);
    await shot(page, "about-en-phone-licences.png");
    await page.setViewportSize({ width: 390, height: 400 });
    const filter = page.getByRole("searchbox", { name: "Filter packages" });
    await filter.fill("react");
    await expect(filter).toBeInViewport();
    // On a short screen the filter bar is not pinned (it would be a third of the height); a rest of rows is in view.
    const position = await filter.evaluate((el) => getComputedStyle(el.closest(".sticky")!).position);
    expect(position).toBe("static");
    expect(await noSideScroll(page)).toBe(true);
  });

  // WCAG 2.4.11: a button reached by Tab is never covered by the top bar, the pinned filter bar or the tab bar.
  for (const height of [844, 600, 400]) {
    test(`phone ${height}: Tab never hides the focused row button under a bar`, async () => {
      await page.setViewportSize({ width: 390, height });
      await page.goto("/about");
      const filter = page.getByRole("searchbox", { name: "Filter packages" });
      await filter.fill("a");
      await filter.focus();
      let seen = 0;
      const covered: string[] = [];
      for (let i = 0; i < 16; i += 1) {
        await page.keyboard.press("Tab");
        const state = await page.evaluate(() => {
          const el = document.activeElement as HTMLElement | null;
          if (!el || !/licence text of/.test(el.getAttribute("aria-label") ?? "")) return null;
          const box = el.getBoundingClientRect();
          const header = document.querySelector("header")!.getBoundingClientRect().bottom;
          const bar = document.querySelector('input[type="search"]')!.closest(".sticky")!;
          const barBottom = getComputedStyle(bar).position === "sticky" ? bar.getBoundingClientRect().bottom : 0;
          const tabs = document.querySelector('nav[aria-label="Tabs"]') as HTMLElement | null;
          const tabsTop = tabs && getComputedStyle(tabs).display !== "none" ? tabs.getBoundingClientRect().top : window.innerHeight;
          const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
          const free = box.top >= Math.max(header, barBottom) - 0.5 && box.bottom <= tabsTop + 0.5 && (hit === el || el.contains(hit));
          return { free, label: el.getAttribute("aria-label"), top: Math.round(box.top), bottom: Math.round(box.bottom), header, barBottom, tabsTop };
        });
        if (state === null) continue;
        seen += 1;
        if (!state.free) covered.push(JSON.stringify(state));
      }
      expect(seen).toBeGreaterThanOrEqual(8);
      expect(covered).toEqual([]);
    });
  }

  // Artefacts for the look at the list: the viewport at the list, light and dark, both layouts (E2E_SHOTS_DIR only).
  for (const scheme of ["light", "dark"] as const) {
    for (const [name, size] of [["desktop", { width: 1280, height: 800 }], ["phone", { width: 390, height: 844 }]] as const) {
      test(`${name} ${scheme}: the list in view`, async () => {
        test.skip(!SHOTS, "artefacts only");
        await page.emulateMedia({ colorScheme: scheme });
        await page.setViewportSize(size);
        await page.goto("/about");
        await page.getByRole("heading", { name: "Third-party software" }).scrollIntoViewIfNeeded();
        await page.getByRole("heading", { name: "Third-party software" }).evaluate((el) => el.scrollIntoView());
        await shot(page, `about-licences-${name}-${scheme}.png`, false);
        await page.getByRole("searchbox", { name: "Filter packages" }).fill("brother");
        await page.getByRole("button", { name: "Show licence text of brother-ql" }).click();
        await page.getByRole("button", { name: "Hide licence text of brother-ql" }).focus();
        await page.keyboard.press("Tab");
        await page.keyboard.press("Shift+Tab");
        await shot(page, `about-licences-${name}-${scheme}-open.png`, false);
        await page.emulateMedia({ colorScheme: null });
      });
    }
  }

  test("phone: the pinned filter bar (390x600) and the unpinned one with the keyboard's height (390x400)", async () => {
    test.skip(!SHOTS, "artefacts only");
    for (const height of [600, 400]) {
      await page.setViewportSize({ width: 390, height });
      await page.goto("/about");
      await page.getByRole("heading", { name: "Third-party software" }).evaluate((el) => el.scrollIntoView());
      await page.getByRole("searchbox", { name: "Filter packages" }).fill("a");
      await page.getByRole("searchbox", { name: "Filter packages" }).focus();
      for (let i = 0; i < 6; i += 1) await page.keyboard.press("Tab");
      await shot(page, `about-licences-phone-h${height}-tab-focus.png`, false);
    }
  });
});

// AGPL section 13 in the installed app: once the service worker controls the page, its navigation fallback
// must not answer the licence link with the app shell (the texts are not precached). The image ships the
// project licence as /licenses/agpl-3.0.txt (backend/Dockerfile); the e2e build gets the same file here.
test.describe("licence link with a real service worker", () => {
  const agpl = resolve(import.meta.dirname, "..", "dist", "licenses", "agpl-3.0.txt");
  let added = false;
  test.beforeAll(() => {
    if (existsSync(agpl)) return;
    copyFileSync(resolve(import.meta.dirname, "..", "..", "LICENSE"), agpl);
    added = true;
  });
  test.afterAll(() => {
    if (added) rmSync(agpl);
  });

  test("Read the licence opens the licence text, not the app", async ({ signedInPage: page }) => {
    await page.evaluate(async () => {
      await navigator.serviceWorker.ready;
    });
    await expect.poll(() => page.evaluate(() => navigator.serviceWorker.controller !== null)).toBe(true);

    await page.goto("/about");
    const [licence] = await Promise.all([
      page.context().waitForEvent("page"),
      page.getByRole("link", { name: "Read the licence" }).click(),
    ]);
    await licence.waitForLoadState();
    expect(await licence.evaluate(() => document.contentType)).toBe("text/plain");
    await expect(licence.locator("body")).toContainText("GNU AFFERO GENERAL PUBLIC LICENSE");
    await licence.close();

    // The same navigation in the controlled tab reaches the server, not the worker's fallback.
    const response = await page.goto("/licenses/agpl-3.0.txt");
    expect(response?.fromServiceWorker()).toBe(false);
    expect(response?.headers()["content-type"]).toMatch(/^text\/plain/);
  });
});
