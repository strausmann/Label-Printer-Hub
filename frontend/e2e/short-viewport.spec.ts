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
const panTo = (page: Page, offsetTop: number) => page.evaluate((t) => (window as unknown as { __pan(t: number): void }).__pan(t), offsetTop);

/** Is the box inside [top, bottom], numbers the test chose (not read back from the stand-in)? */
async function expectWithin(what: Locator, top: number, bottom: number, name: string) {
  const box = await what.boundingBox();
  expect(box, `${name} has a box`).not.toBeNull();
  expect(box!.y, `${name} starts at or below ${top}`).toBeGreaterThanOrEqual(top - 1);
  expect(box!.y + box!.height, `${name} ends at or above ${bottom}`).toBeLessThanOrEqual(bottom + 1);
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
      let top = 0;
      const stand = {
        get height() {
          return height ?? real?.height ?? window.innerHeight;
        },
        get offsetTop() {
          return top;
        },
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
      const api = window as unknown as { __keyboard(h: number | null, offsetTop?: number): void; __pan(offsetTop: number): void };
      // The keyboard opens: the visual viewport gets shorter (and, as on iOS, may sit lower in the layout viewport).
      api.__keyboard = (h, offsetTop = 0) => {
        height = h;
        top = offsetTop;
        target.dispatchEvent(new Event("resize"));
      };
      // The browser scrolls the visual viewport inside the layout viewport: only a `scroll` event, no `resize`.
      api.__pan = (offsetTop) => {
        top = offsetTop;
        target.dispatchEvent(new Event("scroll"));
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
        // Inside a dialog the list uses the room down to the edge of the visible area; the tab bar of a phone is behind the
        // dialog and takes none of it (without the keyboard's help it sits right above the keyboard).
        const edge = (await visible(page)).bottom;
        const listBox = (await list.boundingBox())!;
        expect(edge - (listBox.y + listBox.height), "the list reaches the edge of the visible area").toBeLessThanOrEqual(12 + 6);
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

      /** New sheet with a type chosen: the tallest state of the form, with the keyboard still open. */
      async function openTallAddSheet() {
        const dialog = await openAddSheet();
        const box = dialog.locator('input[role="combobox"]').first();
        await box.click();
        await keyboard(mode);
        await page.keyboard.type(TYPE);
        await page.locator('[role="option"]').first().click();
        // The form now holds the grid, the printer and the placement: it is taller than what is visible.
        const frame = frameOf(dialog);
        await expect.poll(() => frame.evaluate((el) => el.scrollHeight - el.clientHeight)).toBeGreaterThan(100);
        return { dialog, box, frame };
      }

      test("New sheet with a type chosen: the main button and Cancel stay in sight without scrolling", async () => {
        await prepare(mode);
        const { dialog, frame } = await openTallAddSheet();
        await expectInSight(page, frame, "the dialog");
        await expectInSight(page, buttonIn(dialog, "Add sheet"), "the Add sheet button");
        await expectInSight(page, buttonIn(dialog, "Cancel"), "the Cancel button");
      });

      test("New sheet: the list stays open when the dialog frame scrolls (the browser does that to show the field)", async () => {
        await prepare(mode);
        const { box, frame } = await openTallAddSheet();
        await frame.evaluate((el) => (el.scrollTop = 0));
        await box.click();
        const list = page.locator('[role="listbox"]');
        await expect(list).toBeVisible();
        // React Aria closes a non-modal list when an ancestor of the field scrolls; the combobox opens it again.
        await frame.evaluate((el) => (el.scrollTop = 30));
        await expect(list).toBeVisible();
        await expectInSight(page, list, "the list");
      });

      /** The tall form with its type list open, the frame at the top. */
      async function listOpenAtTop() {
        const { box, frame } = await openTallAddSheet();
        await frame.evaluate((el) => (el.scrollTop = 0));
        await box.click();
        const list = page.locator('[role="listbox"]');
        await expect(list).toBeVisible();
        return { box, frame, list };
      }

      test("New sheet: Escape closes the list for good, even while the frame is still scrolling", async () => {
        await prepare(mode);
        const { frame, list } = await listOpenAtTop();
        // The scroll event comes a frame after the key: it must not bring the list back.
        await frame.evaluate((el) => {
          el.scrollTop = 30;
          document.activeElement!.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }));
        });
        await expect(list).toHaveCount(0);
        await page.waitForTimeout(700);
        await expect(list).toHaveCount(0);
      });

      test("New sheet: a choice closes the list for good, even when the form moves under it", async () => {
        await prepare(mode);
        const { box, frame, list } = await listOpenAtTop();
        await box.fill("4731");
        await expect(page.locator('[role="option"]').first()).toBeVisible();
        // The chosen type changes the form (grid, margin check); the frame moves in the same breath as the click.
        await frame.evaluate((el) => {
          document.querySelector<HTMLElement>('[role="option"]')!.click();
          el.scrollTop += 20;
        });
        await page.waitForTimeout(700);
        await expect(list).toHaveCount(0);
        await expect(box).toHaveValue(/4731/);
      });

      const ARROW = '[role="dialog"] button[aria-label="Show all sheet types"]';

      test("New sheet: Enter on the first match closes the list for good, even while the frame is still scrolling", async () => {
        await prepare(mode);
        const { box, frame, list } = await listOpenAtTop();
        await box.fill("4731");
        await expect(page.locator('[role="option"]').first()).toBeVisible();
        await frame.evaluate((el) => {
          el.scrollTop += 20;
          document.activeElement!.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
        });
        await page.waitForTimeout(700);
        await expect(list).toHaveCount(0);
        await expect(box).toHaveValue(/4731/);
      });

      test("New sheet: the arrow that closes the list closes it for good, even while the frame is still scrolling", async () => {
        await prepare(mode);
        const { frame, list } = await listOpenAtTop();
        await frame.evaluate((el, arrow) => {
          document.querySelector<HTMLElement>(arrow)!.click();
          el.scrollTop += 20;
        }, ARROW);
        await page.waitForTimeout(700);
        await expect(list).toHaveCount(0);
      });

      test("New sheet: the arrow that opens the list does not keep a scroll from being undone (the keyboard comes up)", async () => {
        await prepare(mode);
        const { box, frame, list } = await listOpenAtTop();
        await box.press("Escape");
        await expect(list).toHaveCount(0);
        await page.waitForTimeout(400); // past the window in which the Escape counts
        await page.evaluate(() => {
          const w = window as unknown as { __opens: number };
          w.__opens = 0;
          new MutationObserver((records) => {
            for (const r of records)
              for (const n of r.addedNodes) if (n instanceof Element && (n.matches('[role="listbox"]') || n.querySelector('[role="listbox"]'))) w.__opens++;
          }).observe(document.body, { childList: true, subtree: true });
        });
        await page.locator(ARROW).click();
        await expect(list).toBeVisible();
        // The keyboard is up a moment after the press and the browser scrolls the frame to the field.
        await frame.evaluate((el) => (el.scrollTop += 30));
        // Opened by the arrow, closed by the scroll, opened again once it was over: two openings, and it ends open.
        await expect.poll(() => page.evaluate(() => (window as unknown as { __opens: number }).__opens)).toBe(2);
        await expect(list).toBeVisible();
      });

      test("New sheet: a frame that moves 100 ms after a choice does not bring the list back", async () => {
        await prepare(mode);
        const { box, frame, list } = await listOpenAtTop();
        await box.fill("4731");
        await expect(page.locator('[role="option"]').first()).toBeVisible();
        // The form grows under the chosen type and the frame follows, a little after the click.
        await frame.evaluate(async (el) => {
          document.querySelector<HTMLElement>('[role="option"]')!.click();
          await new Promise((resolve) => setTimeout(resolve, 100));
          el.scrollTop += 20;
        });
        await page.waitForTimeout(700);
        await expect(list).toHaveCount(0);
        await expect(box).toHaveValue(/4731/);
      });

      test("New sheet: a scroll that goes on opens the list once, after it has stopped, and once per focus", async () => {
        await prepare(mode);
        const { frame, list } = await listOpenAtTop();
        await page.evaluate(() => {
          const w = window as unknown as { __opens: number };
          w.__opens = 0;
          new MutationObserver((records) => {
            for (const r of records)
              for (const n of r.addedNodes) if (n instanceof Element && (n.matches('[role="listbox"]') || n.querySelector('[role="listbox"]'))) w.__opens++;
          }).observe(document.body, { childList: true, subtree: true });
        });
        const opens = () => page.evaluate(() => (window as unknown as { __opens: number }).__opens);
        // Eight scrolls 70 ms apart (a finger on the frame): the list must stay shut until it is over.
        const duringScroll = await frame.evaluate(async (el) => {
          for (let i = 1; i <= 8; i++) {
            el.scrollTop = i * 12;
            await new Promise((resolve) => setTimeout(resolve, 70));
          }
          return (window as unknown as { __opens: number }).__opens;
        });
        expect(duringScroll, "the list opened between scrolls").toBe(0);
        await expect(list).toBeVisible();
        await page.waitForTimeout(400);
        expect(await opens(), "the list opened exactly once after the scrolling").toBe(1);
        // A second scroll closes it, and it stays closed (once per focus).
        await frame.evaluate((el) => (el.scrollTop = 150));
        await page.waitForTimeout(700);
        await expect(list).toHaveCount(0);
        expect(await opens()).toBe(1);
      });
    });
  }

  // iOS Safari scrolls the layout viewport to show the focused field, so the visual viewport sits lower (offsetTop > 0) and
  // reports it with a `scroll` event only. The numbers are the scenario's; the assertions read where the page really put things.
  const PANNED = [
    { name: "tablet", width: 1280, height: 800 },
    { name: "phone", width: 390, height: 800 },
  ] as const;
  const PAN = { top: 150, height: 420 };
  for (const mode of PANNED) {
    test.describe(`${mode.name}, visual viewport panned to ${PAN.top}`, () => {
      test("a dialog follows the visible area (resize, then a scroll of the visual viewport)", async () => {
        await prepare(mode);
        const dialog = await openAddSheet();
        const frame = frameOf(dialog);
        await page.evaluate(([h]) => (window as unknown as { __keyboard(h: number, t: number): void }).__keyboard(h!, 0), [PAN.height]);
        await panTo(page, PAN.top);
        const overlay = frame.locator("xpath=..");
        await expect.poll(async () => Math.round((await overlay.boundingBox())!.y)).toBe(PAN.top);
        const box = (await overlay.boundingBox())!;
        expect(Math.round(box.height), "the overlay is as tall as the visible area").toBe(PAN.height);
        await expectWithin(frame, PAN.top, PAN.top + PAN.height, "the dialog");
        // The list of the type field lies in the visible area too.
        const field = dialog.locator('input[role="combobox"]').first();
        await field.click();
        await page.keyboard.type(TYPE);
        await expectWithin(page.locator('[role="option"]').first(), PAN.top, PAN.top + PAN.height, "the first option");
        await expectWithin(buttonIn(dialog, "Cancel"), PAN.top, PAN.top + PAN.height, "the Cancel button");
      });

      test("the search results follow the visible area on a phone", async () => {
        test.skip(mode.width > 1000, "the results hang from the top bar on a wide screen");
        await prepare(mode);
        await page.goto("/sheets");
        const search = page.getByRole("combobox", { name: "Search" });
        await search.click();
        await page.evaluate(([h]) => (window as unknown as { __keyboard(h: number, t: number): void }).__keyboard(h!, 0), [PAN.height]);
        await page.keyboard.type("L4736");
        const results = page.getByRole("listbox", { name: "Search results" });
        await expect(results).toBeVisible();
        await panTo(page, PAN.top);
        await expect.poll(async () => (await results.boundingBox())!.y).toBeGreaterThanOrEqual(PAN.top - 1);
        await expectWithin(results, PAN.top, PAN.top + PAN.height, "the results");
      });
    });
  }
});
