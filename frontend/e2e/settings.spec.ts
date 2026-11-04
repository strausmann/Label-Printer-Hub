import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import type { Page } from "@playwright/test";
import { MAIN } from "./env";
import { expect, mainKey, signInWith, test } from "./fixtures";

const SHOTS = process.env.E2E_SHOTS_DIR;
const shot = async (page: Page, name: string, fullPage = false) => {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: resolve(SHOTS, name), fullPage });
};
const noSideScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);

// One sign-in for the whole file: the hub limits sign-ins per minute, and every
// test of every file that signs in counts against the same limit.
test.describe.serial("settings", () => {
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

  test("locked env value cannot be edited", async () => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/settings/integrations");
    const grocy = page.getByRole("group", { name: "Grocy" });
    const url = grocy.getByRole("textbox", { name: "URL" });
    await expect(url).toHaveValue("http://grocy.example.invalid");
    await expect(url).toHaveAttribute("readonly", "");
    await expect(grocy.getByText("Set by the container")).toBeVisible();
    await url.click({ force: true });
    await page.keyboard.type("x");
    await expect(url).toHaveValue("http://grocy.example.invalid");
    // The API agrees: a locked key is refused.
    const answer = await page.evaluate(async () => {
      const session = await (await fetch("/api/v1/auth/session")).json();
      const response = await fetch("/api/v1/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": session.csrf_token },
        body: JSON.stringify({ values: { "integrations.grocy.url": "http://other.example.invalid" } }),
      });
      return response.status;
    });
    expect(answer).toBe(409);
    await shot(page, "task-13-integrations-desktop.png", true);
    await page.setViewportSize({ width: 390, height: 844 });
    await expect.poll(() => noSideScroll(page)).toBe(true);
    await shot(page, "task-13-integrations-phone.png", true);
  });

  test("general: change the display name and see it saved", async () => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/settings");
    await expect(page.getByRole("textbox", { name: "Public URL" })).toHaveAttribute("readonly", "");
    const name = page.getByRole("textbox", { name: "Display name" });
    await name.fill("Workshop Hub");
    await page.getByRole("button", { name: "Save" }).click();
    await expect(page.getByRole("status").filter({ hasText: "Saved" })).toBeVisible();
    await page.reload();
    await expect(page.getByRole("textbox", { name: "Display name" })).toHaveValue("Workshop Hub");
    await shot(page, "task-13-general-desktop.png", true);
    await page.setViewportSize({ width: 390, height: 844 });
    await expect.poll(() => noSideScroll(page)).toBe(true);
    await shot(page, "task-13-general-phone.png", true);
    // Put it back so later tests see the default.
    await page.getByRole("textbox", { name: "Display name" }).fill("Label Printer Hub");
    await page.getByRole("button", { name: "Save" }).click();
    await expect(page.getByRole("status").filter({ hasText: "Saved" })).toBeVisible();
  });

  test("printers: add, edit and disable a printer", async () => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/settings/printers");
    await expect(page.getByText("Workshop PT-P750W")).toBeVisible();
    await shot(page, "task-13-printers-list-desktop.png", true);
    await page.getByRole("button", { name: "Add printer" }).click();
    await page.getByRole("textbox", { name: "Name" }).fill("Shelf QL");
    await page.getByRole("textbox", { name: "Slug" }).fill("shelf-ql");
    await page.getByRole("textbox", { name: "Host" }).fill("192.0.2.30");
    await shot(page, "task-13-printers-form-desktop.png", true);
    await page.getByRole("button", { name: "Create printer" }).click();
    const row = page.getByRole("listitem").filter({ hasText: "Shelf QL" });
    await expect(row).toBeVisible();
    await row.getByRole("button", { name: "Disable Shelf QL" }).click();
    await expect(row.getByText("Disabled", { exact: true })).toBeVisible();
    await page.setViewportSize({ width: 390, height: 844 });
    await expect.poll(() => noSideScroll(page)).toBe(true);
    await shot(page, "task-13-printers-list-phone.png", true);
    await page.getByRole("button", { name: "Edit Shelf QL" }).click();
    await shot(page, "task-13-printers-form-phone.png", true);
  });

  test("access and keys: create a key, see it once, revoke it", async () => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/settings/access");
    await page.getByRole("textbox", { name: "Key name" }).fill("Kept");
    await page.locator("label").filter({ hasText: /^print$/ }).click();
    await expect(page.getByRole("checkbox", { name: "print" })).toBeChecked();
    await shot(page, "task-13-access-desktop.png", true);
    await page.getByRole("button", { name: "Create key" }).click();
    const dialog = page.getByRole("dialog", { name: "Your new key" });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByLabel("Key")).not.toHaveValue("");
    await dialog.getByRole("button", { name: "Done" }).click();
    await expect(dialog).toBeHidden();
    await page.reload();
    const keys = page.getByRole("listitem").filter({ hasText: "Kept" });
    await expect(keys).toBeVisible();
    await page.setViewportSize({ width: 390, height: 844 });
    await expect.poll(() => noSideScroll(page)).toBe(true);
    await shot(page, "task-13-access-phone.png", true);
    await keys.getByRole("button", { name: "Revoke Kept" }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Revoke key" }).click();
    await expect(keys.getByText("Revoked")).toBeVisible();
  });

  test("system: version, health and the log", async () => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/settings/system");
    await expect(page.getByText("Healthy")).toBeVisible();
    await expect(page.getByRole("link", { name: "Download settings" })).toHaveAttribute("href", "/api/v1/settings/export");
    await expect(page.getByRole("link", { name: "API documentation" })).toBeVisible();
    await shot(page, "task-13-system-desktop.png", true);
  });
});
