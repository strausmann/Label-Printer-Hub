import { mkdirSync } from "node:fs";
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

  test("desktop: the third-party list names react and brother-ql, and the text opens on demand", async () => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/about");
    const table = page.getByRole("table");
    await expect(table.getByRole("row", { name: /^react 19/ })).toBeVisible();
    const row = table.getByRole("row", { name: /brother-ql/ });
    await expect(row).toBeVisible();
    await expect(page.getByText("GNU GENERAL PUBLIC LICENSE")).toHaveCount(0);
    await row.getByRole("button", { name: "Show licence text" }).click();
    await expect(page.getByText("GNU GENERAL PUBLIC LICENSE")).toBeVisible();
    // A package that ships no text links its licence id to the SPDX text instead.
    await expect(table.getByRole("row", { name: /fastapi/ }).getByRole("link", { name: "MIT: licence text at SPDX" })).toHaveAttribute("href", "https://spdx.org/licenses/MIT.html");
    await shot(page, "about-en-desktop-licences.png");
  });

  test("desktop: the filter narrows the list", async () => {
    await page.setViewportSize({ width: 1280, height: 500 });
    await page.goto("/about");
    const filter = page.getByRole("textbox", { name: "Filter packages" });
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
    const row = page.getByRole("table").getByRole("row", { name: /brother-ql/ });
    await row.getByRole("button", { name: "Show licence text" }).click();
    await expect(page.getByText("GNU GENERAL PUBLIC LICENSE")).toBeVisible();
    expect(await noSideScroll(page)).toBe(true);
    await shot(page, "about-en-phone-licences.png");
    await page.setViewportSize({ width: 390, height: 400 });
    const filter = page.getByRole("textbox", { name: "Filter packages" });
    await filter.fill("react");
    await expect(filter).toBeInViewport();
    await expect(page.getByRole("table").getByRole("row", { name: /^react/ }).first()).toBeInViewport();
    expect(await noSideScroll(page)).toBe(true);
  });
});
