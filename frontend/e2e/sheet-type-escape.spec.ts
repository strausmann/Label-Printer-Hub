import type { Locator, Page } from "@playwright/test";
import { expect, mainKey, signInWith, test } from "./fixtures";

// Issue #322: a real Escape key press (keydown and keyup) closes the sheet type list, with nothing chosen ("Choose a sheet
// type", "Any sheet type") and with a type chosen, in the New sheet dialog and in the filter of the sheets page. With
// nothing chosen the list used to open again in the same render: Escape stored the label of the "none" entry as the last
// value while the field showed an empty text, and the combobox reopened a focused field whose text differed from it.

const TYPE = "4736";

type Where = { name: string; open: (page: Page) => Promise<Locator> };
const places: Where[] = [
  {
    name: "New sheet dialog",
    open: async (page) => {
      await page.getByRole("button", { name: "New sheet" }).click();
      const dialog = page.getByRole("dialog");
      await expect(dialog).toBeVisible();
      return dialog;
    },
  },
  { name: "sheets page filter", open: async (page) => page.locator("main") },
];

/** The list is closed and stays closed (the reopening came in the same render, a later one would show here too). */
async function expectClosedForGood(page: Page, field: Locator) {
  await expect(page.locator('[role="listbox"]')).toHaveCount(0);
  await expect(field).toHaveAttribute("aria-expanded", "false");
  await page.waitForTimeout(500);
  await expect(page.locator('[role="listbox"]')).toHaveCount(0);
  await expect(field).toBeFocused();
}

test.describe("Escape closes the sheet type list (#322)", () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/");
    await page.evaluate(() => localStorage.setItem("lph.lang", "en"));
    await signInWith(page, mainKey());
    await expect(page.getByRole("navigation", { name: /^(Main|Tabs)$/ }).first()).toBeVisible();
    await page.goto("/sheets");
  });

  for (const where of places) {
    test(`${where.name}, nothing chosen`, async ({ page }) => {
      const scope = await where.open(page);
      const field = scope.getByRole("combobox", { name: "Sheet type" });
      await field.click();
      await expect(page.locator('[role="listbox"]')).toBeVisible();
      await page.keyboard.press("Escape");
      await expectClosedForGood(page, field);
    });

    test(`${where.name}, a type chosen`, async ({ page }) => {
      const scope = await where.open(page);
      const field = scope.getByRole("combobox", { name: "Sheet type" });
      await field.click();
      await page.keyboard.type(TYPE);
      await page.locator('[role="option"]').first().click();
      await expect(field).toHaveValue(new RegExp(TYPE));
      await scope.getByRole("button", { name: "Show all sheet types" }).click();
      await expect(page.locator('[role="listbox"]')).toBeVisible();
      await page.keyboard.press("Escape");
      await expectClosedForGood(page, field);
      await expect(field).toHaveValue(new RegExp(TYPE));
    });
  }
});
