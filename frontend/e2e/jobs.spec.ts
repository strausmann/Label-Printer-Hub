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
const noSideScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);

test.describe("jobs", () => {
  test("retry a failed job", async ({ signedInPage: page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Jobs" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Jobs" })).toBeVisible();
    await shot(page, "task-12-jobs-desktop.png");

    await page.getByRole("radio", { name: "Failed" }).click();
    await page.getByRole("link", { name: "Failed cable label" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Failed cable label" })).toBeVisible();
    await expect(page.getByRole("alert").filter({ hasText: "Printer reported: cover open" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Cancel" })).toHaveCount(0);
    await shot(page, "task-12-job-desktop.png");

    const failedUrl = page.url();
    await page.getByRole("button", { name: "Retry" }).click();
    // The retry is a new job: another address, and it is not the failed one.
    await expect(page).not.toHaveURL(failedUrl);
    await expect(page).toHaveURL(/\/jobs\/[0-9a-f-]{36}$/);
    // The retried job is queued for real now, so its state (and thus a Retry button) depends on
    // what the mock printer does with it; only its identity is asserted here.
    await expect(page.getByRole("heading", { level: 1, name: "Failed cable label" })).toBeVisible();

    await page.setViewportSize({ width: 390, height: 844 });
    await shot(page, "task-12-job-phone.png");
    expect(await noSideScroll(page)).toBe(true);
    await page.getByRole("navigation", { name: "Tabs" }).getByRole("link", { name: "Jobs" }).click();
    await shot(page, "task-12-jobs-phone.png");
    expect(await noSideScroll(page)).toBe(true);
  });
});
