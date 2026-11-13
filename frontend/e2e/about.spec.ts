import { copyFileSync, existsSync, mkdirSync, rmSync } from "node:fs";
import { resolve } from "node:path";
import type { Page } from "@playwright/test";
import { MAIN } from "./env";
import { expect, mainKey, signInWith, test } from "./fixtures";

const SHOTS = process.env.E2E_SHOTS_DIR;
const shot = async (page: Page, name: string) => {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: resolve(SHOTS, name), fullPage: true });
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

  test("phone: the top bar link opens the about page", async () => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    await page.getByRole("banner").getByRole("link", { name: "About and licences" }).click();
    await expect(page).toHaveURL(/\/about$/);
    await expect(page.getByRole("heading", { level: 1, name: "About" })).toBeVisible();
    expect(await noSideScroll(page)).toBe(true);
    await shot(page, "about-en-phone.png");
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
