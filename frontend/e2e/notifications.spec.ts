// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { expect, test } from "./fixtures";

// The seeded hub has one failed job (`E2E_FAILED_JOB_TITLE` of `backend/tests/e2e_app.py`, error "Printer reported:
// cover open"); the browser starts with nothing read.
const FAILED_JOB_TITLE = "Failed cable label";
const FAILED_JOB_ERROR = "Printer reported: cover open";

test.describe("notification centre", () => {
  test("a failing job turns the dot red, the entry opens the job page, mark all read clears the dot", async ({ signedInPage: page }) => {
    const bell = page.getByRole("button", { name: /^Notifications, \d+ unread, the most severe is an error$/ });
    await expect(bell).toBeVisible();
    await expect(bell.locator('svg[data-severity="error"][data-shape="dot"]')).toBeVisible();

    await bell.click();
    const panel = page.getByRole("dialog", { name: "Notifications" });
    await expect(panel.getByRole("button", { name: "Mark all as read" })).toBeFocused();
    const entry = panel.getByRole("link", { name: new RegExp(`${FAILED_JOB_TITLE} failed: ${FAILED_JOB_ERROR}`) }).first();
    await expect(entry).toContainText("New");
    await entry.click();

    await expect(page).toHaveURL(/\/jobs\/[0-9a-f-]{36}$/);
    await expect(panel).toBeHidden();
    await expect(page.getByRole("heading", { level: 1, name: FAILED_JOB_TITLE })).toBeVisible();

    // The panel closed; the entries are still there, read.
    await page.getByRole("button", { name: /^Notifications/ }).click();
    await page.getByRole("dialog", { name: "Notifications" }).getByRole("button", { name: "Mark all as read" }).click();
    await expect(page.getByRole("button", { name: "Notifications, nothing unread", includeHidden: true })).toBeAttached();
    await expect(page.getByRole("dialog", { name: "Notifications" }).getByRole("link", { name: new RegExp(FAILED_JOB_TITLE) }).first()).toBeVisible();
    await expect(page.getByRole("dialog", { name: "Notifications" }).getByText("New")).toHaveCount(0);

    // Escape closes the panel and gives the focus back to the bell.
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog", { name: "Notifications" })).toBeHidden();
    await expect(page.getByRole("button", { name: "Notifications, nothing unread" })).toBeFocused();
  });

  test("read state survives a reload", async ({ signedInPage: page }) => {
    await page.getByRole("button", { name: /^Notifications, \d+ unread/ }).click();
    await page.getByRole("dialog", { name: "Notifications" }).getByRole("button", { name: "Mark all as read" }).click();
    await page.keyboard.press("Escape");
    await page.reload();
    await expect(page.getByRole("button", { name: "Notifications, nothing unread" })).toBeVisible();
  });
});
