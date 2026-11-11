import type { Locator, Page } from "@playwright/test";
import { MAIN } from "./env";
import { expect, mainKey, signInWith, test } from "./fixtures";

// Issue #279: with the on-screen keyboard open, the field, its list and the main buttons of a dialog stay in sight.
//
// Two ways to get a short screen, because a keyboard shrinks the page in two different ways:
//   - "resized": the layout viewport itself gets short (Chromium with `interactive-widget=resizes-content`).
//   - "covered": the layout viewport keeps its size and only `window.visualViewport` shrinks (iOS Safari, older
//     Chromium). Headless Chromium cannot do that, so an init script puts a stand-in in its place that the test
//     resizes like a keyboard would: same properties, same events.

const SCREENS = [
  { name: "tablet 1280x500", width: 1280, height: 500 },
  { name: "phone 390x400", width: 390, height: 400 },
] as const;
const COVERED = [
  { name: "tablet, keyboard covers 1280x800", width: 1280, height: 800, visible: 420 },
  { name: "phone, keyboard covers 390x800", width: 390, height: 800, visible: 380 },
] as const;
const TYPE = "4736";

// While a list is open React Aria hides everything outside it from the accessibility tree, so the role queries would no
// longer find the buttons around it; what a person sees is what these CSS queries find.
const dialogOf = (page: Page) => page.locator('[role="dialog"], [role="alertdialog"]');
/** The box that holds the dialog and scrolls when the dialog is taller than the visible area (the dialog element itself grows with its content). */
const frameOf = (dialog: Locator) => dialog.locator("xpath=..");
const buttonIn = (scope: Locator, name: string) => scope.locator("button").filter({ hasText: new RegExp(`^${name}$`) });

const setLanguage = (page: Page, lang: "de" | "en") => page.evaluate((l) => localStorage.setItem("lph.lang", l), lang);

/** What the person sees: the visual viewport, in layout viewport coordinates. */
const visible = (page: Page) => page.evaluate(() => ({ top: window.visualViewport!.offsetTop, bottom: window.visualViewport!.offsetTop + window.visualViewport!.height, width: window.innerWidth }));

async function expectInSight(page: Page, what: Locator, name: string) {
  const box = await what.boundingBox();
  const view = await visible(page);
  expect(box, `${name} has a box`).not.toBeNull();
  expect(box!.y, `${name} starts below the top of the visible area`).toBeGreaterThanOrEqual(view.top - 1);
  expect(box!.y + box!.height, `${name} ends above the keyboard`).toBeLessThanOrEqual(view.bottom + 1);
}

/** Opens the keyboard in the "covered" mode: only the visual viewport shrinks. */
async function coverWithKeyboard(page: Page, visibleHeight: number) {
  await page.evaluate((h) => (window as unknown as { __keyboard(h: number | null): void }).__keyboard(h), visibleHeight);
}

test.describe("short viewport (on-screen keyboard)", () => {
  let page: Page;
  test.beforeAll(async ({ browser }) => {
    const context = await browser.newContext({ baseURL: MAIN.url });
    // A visualViewport whose height a test can set; without a call it follows the window like the real one.
    await context.addInitScript(() => {
      const real = window.visualViewport;
      const target = new EventTarget();
      let height: number | null = null;
      const stand = {
        get height() {
          return height ?? real?.height ?? window.innerHeight;
        },
        offsetTop: 0,
        offsetLeft: 0,
        pageTop: 0,
        pageLeft: 0,
        scale: 1,
        get width() {
          return window.innerWidth;
        },
        addEventListener: target.addEventListener.bind(target),
        removeEventListener: target.removeEventListener.bind(target),
      };
      Object.defineProperty(window, "visualViewport", { configurable: true, value: stand });
      window.addEventListener("resize", () => target.dispatchEvent(new Event("resize")));
      (window as unknown as { __keyboard(h: number | null): void }).__keyboard = (h) => {
        height = h;
        target.dispatchEvent(new Event("resize"));
      };
    });
    page = await context.newPage();
    await page.goto("/");
    await signInWith(page, mainKey());
    await expect(page.getByRole("navigation", { name: /^(Main|Tabs)$/ }).first()).toBeVisible();
  });
  test.afterAll(async () => {
    await page.context().close();
  });

  type Mode = { name: string; width: number; height: number; visible?: number };
  const modes: Mode[] = [...SCREENS, ...COVERED];

  /** Applies the screen of the mode; for a covered one the keyboard opens when the field has the focus (`keyboard()`). */
  async function prepare(mode: Mode) {
    await setLanguage(page, "en");
    await page.evaluate(() => (window as unknown as { __keyboard(h: number | null): void }).__keyboard(null));
    await page.setViewportSize({ width: mode.width, height: mode.height });
  }
  const keyboard = async (mode: Mode) => {
    if (mode.visible) await coverWithKeyboard(page, mode.visible);
  };

  async function openAddSheet() {
    await page.goto("/sheets");
    await page.getByRole("button", { name: "New sheet" }).click();
    const dialog = dialogOf(page);
    await expect(dialog).toBeVisible();
    return dialog;
  }

  for (const mode of modes) {
    test.describe(mode.name, () => {
      test("New sheet: typed type, first option, and both buttons are in sight", async () => {
        await prepare(mode);
        const dialog = await openAddSheet();
        const box = dialog.locator('input[role="combobox"]').first();
        await box.click();
        await keyboard(mode);
        await page.keyboard.type(TYPE);
        await expectInSight(page, box, "the sheet type field");
        const first = page.locator('[role="option"]').first();
        await expect(first).toBeVisible();
        await expectInSight(page, first, "the first option");
        await expectInSight(page, buttonIn(dialog, "Cancel"), "the Cancel button");
        await expectInSight(page, buttonIn(dialog, "Add sheet"), "the Add sheet button");
        await expectInSight(page, frameOf(dialog), "the dialog");
      });

      test("New sheet: after clearing the field the whole list is there and scrolls inside the visible area", async () => {
        await prepare(mode);
        const dialog = await openAddSheet();
        const box = dialog.locator('input[role="combobox"]').first();
        await box.click();
        await keyboard(mode);
        await page.keyboard.type(TYPE);
        await expect(page.locator('[role="option"]').first()).toBeVisible();
        await box.fill("");
        const options = page.locator('[role="option"]');
        // The list is long again: the placeholder entry and the types.
        await expect.poll(() => options.count()).toBeGreaterThan(4);
        // Several options are in sight at once, not just the placeholder entry.
        const inSight = async () => {
          const view = await visible(page);
          let n = 0;
          for (const o of await options.all()) {
            const b = await o.boundingBox();
            if (b && b.y >= view.top - 1 && b.y + b.height <= view.bottom + 1) n++;
          }
          return n;
        };
        await expect.poll(inSight).toBeGreaterThanOrEqual(3);
        // The rest is reachable by scrolling the list, and it stays inside the visible area.
        const list = page.locator('[role="listbox"]');
        await expectInSight(page, list, "the list");
        await list.evaluate((el) => (el.scrollTop = el.scrollHeight));
        await expectInSight(page, options.last(), "the last option after scrolling");
      });

      test("Import a sheet type: the text, the file field and both buttons are reachable", async () => {
        await prepare(mode);
        await page.goto("/sheets/archive");
        await page.getByRole("button", { name: "Import type" }).click();
        const dialog = dialogOf(page);
        const text = dialog.getByRole("textbox", { name: "Export file contents" });
        await text.click();
        await keyboard(mode);
        await text.fill('{"format":"x"}');
        await expectInSight(page, frameOf(dialog), "the dialog");
        // The dialog scrolls inside itself: its buttons are reachable there and then in sight.
        const import_ = buttonIn(dialog, "Import");
        await import_.scrollIntoViewIfNeeded();
        await expectInSight(page, import_, "the Import button");
        await expectInSight(page, buttonIn(dialog, "Cancel"), "the Cancel button");
        await page.keyboard.press("Escape");
      });

      test("Global search: the field and the first result are in sight", async () => {
        await prepare(mode);
        await page.goto("/sheets");
        const search = page.getByRole("combobox", { name: "Search" });
        await search.click();
        await keyboard(mode);
        await page.keyboard.type("L4736");
        await expectInSight(page, search, "the search field");
        const first = page.getByRole("listbox", { name: "Search results" }).getByRole("option").first();
        await expect(first).toBeVisible();
        await expectInSight(page, first, "the first result");
      });

      test("Discard sheet (a confirmation): its buttons are in sight", async () => {
        await prepare(mode);
        await page.goto("/sheets");
        await page.getByRole("button", { name: /Discard/ }).first().click();
        const dialog = dialogOf(page);
        await expect(dialog).toBeVisible();
        await keyboard(mode);
        await expectInSight(page, frameOf(dialog), "the dialog");
        await buttonIn(dialog, "Cancel").scrollIntoViewIfNeeded();
        await expectInSight(page, buttonIn(dialog, "Cancel"), "the Cancel button");
        await page.keyboard.press("Escape");
      });
    });
  }
});
