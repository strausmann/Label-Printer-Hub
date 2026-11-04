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

test.describe("lookup", () => {
  test("opening /asset/<id> shows the item and prints it", async ({ signedInPage: page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/asset/42");
    await expect(page.getByRole("heading", { level: 1, name: "Snipe-IT item" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Open in Snipe-IT" })).toHaveAttribute("href", "https://example.invalid/snipeit/42");
    const preview = page.getByRole("img", { name: "Label preview" });
    await expect(preview).toBeVisible();
    // The preview is a real picture from the layout engine, not a broken image.
    expect(await preview.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0)).toBe(true);
    await shot(page, "task-12-item-desktop.png");

    await page.getByRole("button", { name: "Print now" }).click();
    await expect(page.getByText(/Sent to Workshop PT-P750W/)).toBeVisible();
    await page.getByRole("link", { name: "View the job" }).click();
    await expect(page).toHaveURL(/\/jobs\/[0-9a-f-]{36}$/);
    await expect(page.getByRole("heading", { level: 1, name: "Snipe-IT item" })).toBeVisible();

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/spool/7");
    await expect(page.getByRole("heading", { level: 1, name: "Spoolman item" })).toBeVisible();
    await expect(page.getByRole("img", { name: "Label preview" })).toBeVisible();
    await shot(page, "task-12-item-phone.png");
    expect(await noSideScroll(page)).toBe(true);
  });

  test("the cart collects items from QR paths and prints them as one batch", async ({ signedInPage: page }) => {
    await page.goto("/product/3");
    await page.getByRole("button", { name: "Add to cart" }).click();
    await page.goto("/loc/5");
    await page.getByRole("button", { name: "Add to cart" }).click();
    await page.getByRole("link", { name: "Cart (2)" }).click();
    await expect(page.getByRole("list", { name: "Cart" }).getByRole("listitem")).toHaveCount(2);

    // A reload keeps the cart (it lives in this browser).
    await page.reload();
    await expect(page.getByRole("list", { name: "Cart" }).getByRole("listitem")).toHaveCount(2);

    await page.getByRole("button", { name: "Print 2 labels" }).click();
    await expect(page.getByText(/2 labels sent to Workshop PT-P750W/)).toBeVisible();
    await expect(page.getByText("The cart is empty.")).toBeVisible();
  });
});
