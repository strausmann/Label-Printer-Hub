import type { Browser, Page } from "@playwright/test";
import { MAIN } from "./env";
import { expect, mainKey, signInWith, test } from "./fixtures";

// Issue #318: on a phone a dialog has a close button, and one tap on the dim area around it closes it, also while the list
// of a combobox inside it is open. Before the fix that tap closed nothing: React Aria closes only the top-most overlay, the
// open list was it and is not dismissable, and the dialog's focus scope put the focus back into the field, which opened its
// list (and, on a phone, the keyboard) again.

const dialogOf = (page: Page) => page.locator('[role="dialog"], [role="alertdialog"]');
const fieldIn = (page: Page) => page.locator('[role="dialog"] input[role="combobox"]').first();

/** Counts the times the sheet type field gets the focus: each one brings a phone's keyboard up. */
async function countFieldFocus(page: Page) {
  await page.evaluate(() => {
    const w = window as unknown as { __fieldFocus: number };
    w.__fieldFocus = 0;
    document.addEventListener("focusin", (e) => {
      if (e.target instanceof HTMLInputElement && e.target.getAttribute("role") === "combobox" && e.target.closest('[role="dialog"]')) w.__fieldFocus++;
    });
  });
  return () => page.evaluate(() => (window as unknown as { __fieldFocus: number }).__fieldFocus);
}

/** What has the focus once the dialog is gone: never something that was inside it. */
async function expectNothingInsideFocused(page: Page) {
  const active = await page.evaluate(() => {
    const a = document.activeElement;
    return { inDialog: !!a?.closest('[role="dialog"], [role="alertdialog"]'), combobox: a?.getAttribute("role") === "combobox", connected: !!a?.isConnected };
  });
  expect(active.inDialog, "the focus is not inside a dialog").toBe(false);
  expect(active.combobox, "no combobox has the focus").toBe(false);
}

async function phone(browser: Browser) {
  const context = await browser.newContext({ baseURL: MAIN.url, hasTouch: true, isMobile: true, viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  await page.goto("/");
  await page.evaluate(() => localStorage.setItem("lph.lang", "en"));
  await signInWith(page, mainKey());
  await expect(page.getByRole("navigation", { name: /^(Main|Tabs)$/ }).first()).toBeVisible();
  return page;
}

test.describe("phone 390x844, touch", () => {
  let page: Page;
  test.beforeAll(async ({ browser }) => {
    page = await phone(browser);
  });
  test.afterAll(async () => {
    await page.context().close();
  });

  async function openNewSheet() {
    await page.goto("/sheets");
    await page.getByRole("button", { name: "New sheet" }).tap();
    await expect(dialogOf(page)).toBeVisible();
  }
  /** A tap on the dim area: the top-left corner, outside the dialog box. */
  const tapBackdrop = () => page.touchscreen.tap(8, 8);

  // The keyboard of a phone closes without taking the focus from the field: the list stays open. That is the state the
  // maintainer saw (#318); the other two are the ways out of the list the issue names.
  const ways = [
    { name: "with the list still open (the keyboard closed)", leave: async () => {} },
    { name: "after Escape on the list", leave: () => page.keyboard.press("Escape") },
    { name: "after a tap on the dialog heading", leave: () => page.locator('[role="dialog"] :is(h1, h2, h3)').first().tap() },
  ];
  for (const way of ways) {
    test(`New sheet: one tap on the dim area closes the dialog ${way.name}, and nothing inside it is focused`, async () => {
      await openNewSheet();
      await fieldIn(page).tap();
      await expect(page.locator('[role="listbox"]')).toBeVisible();
      await way.leave();
      const focusCount = await countFieldFocus(page);
      await tapBackdrop();
      await expect(dialogOf(page)).toHaveCount(0);
      await expect(page.locator('[role="listbox"]')).toHaveCount(0);
      expect(await focusCount(), "the field was not given the focus again (no keyboard)").toBe(0);
      await expectNothingInsideFocused(page);
      await expect(page).toHaveURL(/\/sheets$/);
    });
  }

  test("New sheet: the close button is in the top-right corner, 44 x 44, next to the title, and closes the dialog", async () => {
    await openNewSheet();
    const dialog = dialogOf(page);
    const close = dialog.getByRole("button", { name: "Close", exact: true }).first();
    // Measured once the dialog has stopped scaling in.
    await page.waitForFunction(() => document.getAnimations().every((a) => a.playState !== "running"));
    const box = (await close.boundingBox())!;
    expect(Math.round(box.width)).toBeGreaterThanOrEqual(44);
    expect(Math.round(box.height)).toBeGreaterThanOrEqual(44);
    const frame = (await dialog.locator("xpath=..").boundingBox())!;
    // In the top-right corner of the dialog box.
    expect(frame.x + frame.width - (box.x + box.width), "near the right edge").toBeLessThanOrEqual(24);
    expect(box.y - frame.y, "near the top edge").toBeLessThanOrEqual(24);
    // The title is beside it, not under it.
    const title = (await dialog.locator(":is(h1, h2, h3)").first().boundingBox())!;
    expect(title.x + title.width, "the title ends before the button").toBeLessThanOrEqual(box.x + 1);
    await close.tap();
    await expect(dialog).toHaveCount(0);
    await expectNothingInsideFocused(page);
  });

  test("Discard sheet (an alert): no close button, and a tap on the dim area leaves it open", async () => {
    await page.goto("/sheets");
    await page.getByRole("button", { name: /Discard/ }).first().tap();
    const dialog = page.getByRole("alertdialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Close", exact: true })).toHaveCount(0);
    await tapBackdrop();
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "Cancel" }).tap();
    await expect(dialog).toHaveCount(0);
  });
});

test("desktop: a click on the dim area closes New sheet while its list is open", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");
  await page.evaluate(() => localStorage.setItem("lph.lang", "en"));
  await signInWith(page, mainKey());
  await page.goto("/sheets");
  await page.getByRole("button", { name: "New sheet" }).click();
  await fieldIn(page).click();
  await expect(page.locator('[role="listbox"]')).toBeVisible();
  await page.mouse.click(8, 8);
  await expect(dialogOf(page)).toHaveCount(0);
  await expectNothingInsideFocused(page);
});
