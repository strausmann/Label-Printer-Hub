// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import type { Page } from "@playwright/test";
import { expect, test } from "./fixtures";

const SHOTS = process.env.E2E_SHOTS_DIR;
const shot = async (page: Page, name: string, fullPage = false) => {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: resolve(SHOTS, name), fullPage });
};
const noSideScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);

test.describe("integrations", () => {
  test("sidebar Snipe-IT, enter 42, the item view opens", async ({ signedInPage: page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Snipe-IT" }).click();
    await expect(page).toHaveURL(/\/integrations\/snipeit$/);
    await expect(page.getByRole("heading", { level: 1, name: "Snipe-IT" })).toBeVisible();
    await expect(page.getByRole("main").getByText("Configured", { exact: true })).toBeVisible();
    await expect(page.getByRole("textbox", { name: "Find an asset or location" })).toBeFocused();
    await shot(page, "eint-snipeit-desktop-empty.png");

    await page.getByRole("textbox", { name: "Find an asset or location" }).fill("42");
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/lookup\/snipeit\/42$/);
    await expect(page.getByRole("heading", { level: 1, name: "Snipe-IT item" })).toBeVisible();

    // The item is now in the recent list of the start page, and survives a reload.
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Snipe-IT" }).click();
    const recent = page.getByRole("list", { name: "Recently opened" });
    await expect(recent.getByRole("listitem")).toHaveCount(1);
    await page.reload();
    await expect(recent.getByRole("listitem")).toHaveCount(1);
    await expect(recent.getByText("42")).toBeVisible();
    await shot(page, "eint-snipeit-desktop.png");

    await page.setViewportSize({ width: 390, height: 844 });
    await expect(recent.getByRole("listitem")).toHaveCount(1);
    await shot(page, "eint-snipeit-phone.png");
    expect(await noSideScroll(page)).toBe(true);
  });

  test("the global search offers a lookup per integration and Enter opens the first", async ({ signedInPage: page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.getByRole("combobox", { name: "Search" }).fill("HH-AK0042");
    const options = page.getByRole("option");
    await expect(options).toHaveCount(3);
    await expect(options.first()).toHaveText("Look up HH-AK0042 in Snipe-IT");
    await shot(page, "eint-search-desktop.png");

    await page.setViewportSize({ width: 390, height: 844 });
    await expect(options).toHaveCount(3);
    await shot(page, "eint-search-phone.png");
    expect(await noSideScroll(page)).toBe(true);
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/lookup\/snipeit\/HH-AK0042$/);
  });

  test("phone: the Overview has an Integrations tile per app and the start page fits", async ({ signedInPage: page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    const tiles = page.getByRole("region", { name: "Integrations" });
    await expect(tiles).toBeVisible();
    await expect(tiles.getByRole("link")).toHaveCount(3);
    await tiles.evaluate((el) => el.scrollIntoView({ block: "center" }));
    await shot(page, "eint-overview-phone.png");
    expect(await noSideScroll(page)).toBe(true);

    await tiles.getByRole("link", { name: /Grocy/ }).click();
    await expect(page).toHaveURL(/\/integrations\/grocy$/);
    await expect(page.getByRole("textbox", { name: "Find a product" })).toBeVisible();
    await shot(page, "eint-grocy-phone.png");
    expect(await noSideScroll(page)).toBe(true);
  });

  test("a pasted label link is routed to its item", async ({ signedInPage: page }) => {
    await page.goto("/integrations/grocy");
    const field = page.getByRole("textbox", { name: "Find a product" });
    await field.fill("https://hub.example.invalid/spool/7");
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/lookup\/spoolman\/7$/);
    await expect(page.getByRole("heading", { level: 1, name: "Spoolman item" })).toBeVisible();
  });
});
