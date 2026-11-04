import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import type { Page } from "@playwright/test";
import { expect, test } from "./fixtures";

const SHOTS = process.env.E2E_SHOTS_DIR;
const shot = async (page: Page, name: string) => {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: resolve(SHOTS, name), fullPage: true });
};

test.describe("printers", () => {
  test("pausing a printer changes its badge through the event stream, without a reload", async ({
    signedInPage: page,
  }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Printers" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Printers" })).toBeVisible();
    await page.getByRole("link", { name: /Workshop PT-P750W/ }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Workshop PT-P750W" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Pause" })).toBeVisible();
    await shot(page, "task-11-detail-desktop.png");

    // Marker on the window: a reload would erase it.
    await page.evaluate(() => ((window as unknown as { __kept: boolean }).__kept = true));
    await page.getByRole("button", { name: "Pause" }).click();
    await expect(page.getByRole("button", { name: "Resume" })).toBeVisible();
    await expect(page.getByText("Paused").first()).toBeVisible();
    expect(await page.evaluate(() => (window as unknown as { __kept?: boolean }).__kept)).toBe(true);

    // The same change reaches the overview (a paused printer needs attention) …
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Overview" }).click();
    const attention = page.getByRole("region", { name: "Needs attention" });
    await expect(attention.getByText("Workshop PT-P750W")).toBeVisible();
    await shot(page, "task-11-overview-desktop.png");

    // … and resuming from there flips it back.
    await attention.getByRole("button", { name: "Resume Workshop PT-P750W" }).click();
    await expect(attention.getByText("Workshop PT-P750W")).toHaveCount(0);

    await page.setViewportSize({ width: 390, height: 844 });
    await shot(page, "task-11-overview-phone.png");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.getByRole("navigation", { name: "Tabs" }).getByRole("link", { name: "Printers" }).click();
    await page.getByRole("link", { name: /Office QL-820NWB/ }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Office QL-820NWB" })).toBeVisible();
    await shot(page, "task-11-detail-phone.png");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  });

  test("the overview answers its three questions in order", async ({ signedInPage: page }) => {
    const headings = page.getByRole("heading", { level: 2 });
    await expect(headings.nth(0)).toHaveText("Printing now");
    await expect(headings.nth(1)).toHaveText("Needs attention");
    await expect(headings.nth(2)).toHaveText("Material");
  });
});
