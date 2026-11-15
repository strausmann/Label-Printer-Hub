// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

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

/** Fills the cart of the browser (the key and the shape are those of `features/lookup/cart.ts`) with `entries` lines. */
const putInCart = (page: Page, entries: number) =>
  page.evaluate((n) => {
    const line = (id: number) => ({ app: "grocy", id: String(id), name: `Item ${id}`, content_type: "qr_two_lines", copies: 4 });
    localStorage.setItem("lph.cart", JSON.stringify(Array.from({ length: n }, (_, i) => line(i + 1))));
  }, entries);
const emptyCart = (page: Page) => page.evaluate(() => localStorage.removeItem("lph.cart"));

type Box = { x: number; y: number; width: number; height: number };
const intersects = (a: Box, b: Box) =>
  a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;

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
  /** Below 1024 px the search is a magnifier that opens a dialog (#320); from there on it is the inline field. */
  const isPhone = (mode: Mode) => mode.width < 1024;
  const searchField = () => page.getByRole("combobox", { name: "Search" });
  /** Puts the focus into the search field: the inline one, or the one in the dialog the magnifier opens. */
  async function focusSearch(mode: Mode) {
    if (isPhone(mode)) {
      await page.locator("header").getByRole("button", { name: "Search", exact: true }).click();
      await expect(page.getByRole("dialog", { name: "Search" })).toBeVisible();
      await expect(searchField()).toBeFocused();
    } else {
      await searchField().click();
    }
  }

  async function openAddSheet() {
    await page.goto("/sheets");
    await page.getByRole("button", { name: "New sheet" }).click();
    const dialog = dialogOf(page);
    await expect(dialog).toBeVisible();
    return dialog;
  }

  test("Top bar at 320 px: the cart badge overlaps no other control", async () => {
    await prepare({ name: "narrow", width: 320, height: 640 });
    await page.goto("/sheets");
    // The widest badge: more than 99 entries.
    await putInCart(page, 120);
    await page.reload();
    const header = page.locator("header");
    const cart = header.getByRole("link", { name: "Cart, 120 items" });
    await expect(cart).toBeVisible();
    await expect(cart).toContainText("99+");
    // Below 1024 px About, the theme and Sign out live in the menu (#319); the top bar keeps Menu, the Search magnifier, the bell and the cart.
    const controls: Array<[string, Locator]> = [
      ["the menu button", header.getByRole("button", { name: "Menu", exact: true })],
      ["the search button", header.getByRole("button", { name: "Search", exact: true })],
      ["the bell", header.getByRole("button", { name: /^Notifications/ })],
      ["the cart", cart],
    ];
    for (const gone of [header.getByRole("link", { name: /^About/ }), header.getByRole("button", { name: /^Theme: / }), header.getByRole("button", { name: "Sign out" })]) {
      await expect(gone).toBeHidden();
    }
    const boxes: Array<{ name: string; box: Box }> = [];
    for (const [name, control] of controls) {
      const box = await control.boundingBox();
      expect(box, `${name} has a box`).not.toBeNull();
      expect(box!.x, `${name} starts inside the screen`).toBeGreaterThanOrEqual(0);
      expect(box!.x + box!.width, `${name} ends inside the screen`).toBeLessThanOrEqual(320 + 1);
      boxes.push({ name, box: box! });
    }
    // The badge is a child of the cart link: its own box must also stay inside the link's box.
    const badge = (await cart.getByTestId("cart-badge").boundingBox())!;
    const link = (await cart.boundingBox())!;
    expect(badge.x).toBeGreaterThanOrEqual(link.x - 1);
    expect(badge.x + badge.width).toBeLessThanOrEqual(link.x + link.width + 1);
    boxes.forEach((first, i) => {
      for (const second of boxes.slice(i + 1)) {
        expect(intersects(first.box, second.box), `${first.name} and ${second.name} do not overlap`).toBe(false);
      }
    });
    await emptyCart(page);
  });

  for (const mode of modes) {
    test.describe(mode.name, () => {
      // The menu button is a phone control (hidden from 1024 px up): the tablet-wide modes have no menu to test.
      test("Phone menu: the close button and the first entry are in sight, the list scrolls inside the sheet", async () => {
        test.skip(mode.width >= 1024, "no menu button on a wide screen");
        await prepare(mode);
        await page.goto("/");
        await page.getByRole("button", { name: "Menu", exact: true }).click();
        const menu = page.getByRole("dialog", { name: "Menu" });
        await expect(menu).toBeVisible();
        await keyboard(mode);
        const sheet = menu.getByTestId("menu-scroll");
        const close = menu.locator('button[aria-label="Close"]');
        const first = menu.locator('nav[aria-label="Pages"] a').first();
        await expectInSight(page, close, "the close button");
        await expectInSight(page, first, "the first entry");
        await expectInSight(page, menu.locator('button[aria-label="Sign out"]'), "the Sign out button");
        await expectInSight(page, sheet, "the sheet");
        // More entries than fit: the sheet scrolls, the page behind does not move.
        const scroll = await sheet.evaluate((el) => ({ over: el.scrollHeight > el.clientHeight, page: window.scrollY }));
        expect(scroll.over, "the list is taller than the visible area and scrolls inside the sheet").toBe(true);
        const last = menu.locator('nav[aria-label="Pages"] a').last();
        await last.scrollIntoViewIfNeeded();
        await expectInSight(page, last, "the last entry after scrolling");
        await expectInSight(page, close, "the close button after scrolling");
        // The footer is pinned: reachable without scrolling the list, before and after.
        await expectInSight(page, menu.locator('button[aria-label="Sign out"]'), "the Sign out button after scrolling");
        expect(await page.evaluate(() => window.scrollY), "the page behind stays put").toBe(scroll.page);
        await page.keyboard.press("Escape");
        await expect(menu).toBeHidden();
      });

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
        test.skip(isPhone(mode), "a phone has the search dialog, see the next case");
        await prepare(mode);
        await page.goto("/sheets");
        const search = searchField();
        await search.click();
        await keyboard(mode);
        await page.keyboard.type("L4736");
        await expectInSight(page, search, "the search field");
        const first = page.getByRole("listbox", { name: "Search results" }).getByRole("option").first();
        await expect(first).toBeVisible();
        await expectInSight(page, first, "the first result");
      });

      test("Search dialog: the field, the first result and the close button are in sight", async () => {
        test.skip(!isPhone(mode), "a wide screen keeps the inline field, see the case above");
        await prepare(mode);
        await page.goto("/sheets");
        await focusSearch(mode);
        await keyboard(mode);
        await page.keyboard.type("L4736");
        const dialog = page.getByRole("dialog", { name: "Search" });
        const first = page.getByRole("listbox", { name: "Search results" }).getByRole("option").first();
        await expect(first).toBeVisible();
        await expectInSight(page, searchField(), "the search field");
        await expectInSight(page, first, "the first result");
        await expectInSight(page, dialog.getByRole("button", { name: "Close" }), "the close button");
        await expectInSight(page, dialog, "the dialog");
        // The first Escape closes the results, the second the dialog; the magnifier has the focus again.
        await page.keyboard.press("Escape");
        await expect(page.getByRole("listbox")).toHaveCount(0);
        await expect(dialog).toBeVisible();
        await page.keyboard.press("Escape");
        await expect(dialog).toBeHidden();
        await expect(page.locator("header").getByRole("button", { name: "Search", exact: true })).toBeFocused();
      });

      test("Notifications: the actions and the first entry are in sight", async () => {
        await prepare(mode);
        await page.goto("/sheets");
        // The search field has the focus and the keyboard is up (a covered mode shrinks the visual viewport only).
        await focusSearch(mode);
        await keyboard(mode);
        // On a phone the search dialog covers the bell: closing it leaves the keyboard-sized screen as it is.
        if (isPhone(mode)) {
          await page.keyboard.press("Escape");
          await expect(page.getByRole("dialog")).toBeHidden();
        }
        await page.getByRole("button", { name: /^Notifications/ }).click();
        const panel = dialogOf(page);
        await expect(panel).toBeVisible();
        const first = panel.getByRole("link").first();
        await expect(first).toBeVisible();
        await expectInSight(page, buttonIn(panel, "Mark all as read"), "the Mark all as read button");
        await expectInSight(page, buttonIn(panel, "Clear all"), "the Clear all button");
        await expectInSight(page, first, "the first entry");
        await expectInSight(page, panel, "the panel");
        await page.keyboard.press("Escape");
        await expect(panel).toBeHidden();
      });

      test("with the search keyboard up the cart icon stays in sight", async () => {
        await prepare(mode);
        await page.goto("/sheets");
        await putInCart(page, 3);
        await page.reload();
        await focusSearch(mode);
        await keyboard(mode);
        const cart = page.locator("header").getByRole("link", { name: "Cart, 3 items" });
        await expect(cart).toBeVisible();
        await expectInSight(page, cart, "the cart icon");
        await emptyCart(page);
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

      test("Resolve all (a confirmation): its buttons are in sight", async () => {
        await prepare(mode);
        await page.goto("/sheets/L4736-0005");
        await page.getByRole("button", { name: "Resolve all as printed" }).click();
        const dialog = dialogOf(page);
        await expect(dialog).toBeVisible();
        await keyboard(mode);
        await expectInSight(page, frameOf(dialog), "the dialog");
        await buttonIn(dialog, "Resolve as printed").scrollIntoViewIfNeeded();
        await expectInSight(page, buttonIn(dialog, "Resolve as printed"), "the Resolve as printed button");
        await buttonIn(dialog, "Cancel").scrollIntoViewIfNeeded();
        await expectInSight(page, buttonIn(dialog, "Cancel"), "the Cancel button");
        await page.keyboard.press("Escape");
      });

      test("Printer form: the community field and the Save button can be brought into sight (inline form, page scrolls)", async () => {
        await prepare(mode);
        await page.goto("/settings/printers");
        await page.getByRole("button", { name: "Add printer" }).click();
        const form = page.getByRole("form", { name: "Add a printer" });
        const field = form.getByLabel("SNMP community");
        await field.click();
        await keyboard(mode);
        await page.keyboard.type("bench");
        // The browser scrolls the focused field into the visible area; the stand-in for a "covered" keyboard does not, so the
        // test does it: the page must be able to scroll far enough for the field (and then the button) to reach the top.
        await field.evaluate((el) => el.scrollIntoView({ block: "start" }));
        await expectInSight(page, field, "the SNMP community field");
        const save = form.getByRole("button", { name: "Create printer" });
        await save.evaluate((el) => el.scrollIntoView({ block: "start" }));
        await expectInSight(page, save, "the Create printer button");
      });

      test("Grocy labels: a printer list and the Save button can be brought into sight (inline panel, page scrolls)", async () => {
        await prepare(mode);
        await page.goto("/settings/integrations");
        const panel = page.getByRole("group", { name: "Grocy labels" });
        const recipe = panel.getByRole("group", { name: "Recipe" });
        const printer = recipe.getByRole("button", { name: /Printer$/ });
        await printer.evaluate((el) => el.scrollIntoView({ block: "start" }));
        // A select is a button: tapping it opens no keyboard (and closes one that was open), so its list is checked on
        // the screen as it is. On a short screen the list must still fit what is visible.
        await printer.click();
        await expectInSight(page, page.locator('[role="option"]').first(), "the first printer option");
        await page.keyboard.press("Escape");
        // The keyboard opened by a field of this page (the Grocy URL above) must not hide the panel's buttons for good.
        await keyboard(mode);
        const save = panel.getByRole("button", { name: "Save" });
        await save.evaluate((el) => el.scrollIntoView({ block: "start" }));
        await expectInSight(page, save, "the Save button of the Grocy labels");
        const copy = panel.getByRole("button", { name: "Copy lines" });
        await copy.evaluate((el) => el.scrollIntoView({ block: "start" }));
        if (mode.visible) {
          // The button is near the end of the page, which cannot scroll further: with the layout viewport left at full
          // height, the browser pans the visual viewport down instead (a `scroll` of the visual viewport, no `resize`).
          const box = (await copy.boundingBox())!;
          const height = mode.visible;
          if (box.y + box.height > height) await panTo(page, Math.min(mode.height - height, Math.ceil(box.y + box.height - height)));
        }
        await expectInSight(page, copy, "the Copy lines button");
        await panTo(page, 0);
      });

      test("Grocy labels: the sheet type list of a page printer and the Save button can be brought into sight", async () => {
        await prepare(mode);
        await page.goto("/settings/integrations");
        const panel = page.getByRole("group", { name: "Grocy labels" });
        const battery = panel.getByRole("group", { name: "Battery" });
        const printer = battery.getByRole("button", { name: /Printer$/ });
        await printer.evaluate((el) => el.scrollIntoView({ block: "start" }));
        await printer.click();
        await page.getByRole("option", { name: "Office page printer" }).click();
        const sheetType = battery.getByRole("button", { name: /Sheet type$/ });
        await sheetType.evaluate((el) => el.scrollIntoView({ block: "start" }));
        await expectInSight(page, sheetType, "the sheet type field");
        // A select opens no keyboard; on a short screen its list must still fit what is visible.
        await sheetType.click();
        await expectInSight(page, page.locator('[role="option"]').first(), "the first sheet type");
        await page.keyboard.press("Escape");
        await keyboard(mode);
        const save = panel.getByRole("button", { name: "Save" });
        await save.evaluate((el) => el.scrollIntoView({ block: "start" }));
        await expectInSight(page, save, "the Save button of the Grocy labels");
        // Nothing was saved: the next test loads the page again with the stored values.
      });

      test("Select: with the keyboard up, a select near the bottom shows its trigger and first option in sight", async () => {
        test.skip(!mode.visible, "the keyboard covers the screen only in the covered modes");
        await prepare(mode);
        await page.goto("/settings/integrations");
        const panel = page.getByRole("group", { name: "Grocy labels" });
        const printer = panel.getByRole("group", { name: "Recipe" }).getByRole("button", { name: /Printer$/ });
        await printer.scrollIntoViewIfNeeded();
        await coverWithKeyboard(page, mode.visible!);
        // Place the trigger deterministically just above the keyboard, so the list has to open upwards.
        const placed = await printer.boundingBox();
        const view = await visible(page);
        await page.evaluate((dy) => window.scrollBy(0, dy), placed!.y + placed!.height - (view.bottom - 10));
        // A mispositioned run fails here, not later.
        await expectWithin(printer, view.bottom - 60, view.bottom, "the Printer select");
        await printer.click();
        await expectInSight(page, printer, "the Printer select");
        await expectInSight(page, page.locator('[role="option"]').first(), "the first printer option");
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

      test("New sheet: a list opened right after Escape is still brought back after a scroll (the mark of the Escape is stale)", async () => {
        await prepare(mode);
        const { frame, list } = await listOpenAtTop();
        await page.evaluate(() => {
          const w = window as unknown as { __opens: number };
          w.__opens = 0;
          // An opening is the field saying it is expanded. Counting the list nodes that are added would miss an opening whose
          // popover was still leaving: the same node then stays and no node is added.
          new MutationObserver((records) => {
            for (const r of records) if (r.target instanceof HTMLInputElement && r.target.getAttribute("aria-expanded") === "true") w.__opens++;
          }).observe(document.body, { attributes: true, subtree: true, attributeFilter: ["aria-expanded"] });
        });
        // All within 300 ms: Escape closes, the arrow opens, the keyboard scrolls the frame. The arrow opens the list, so the
        // Escape before it must not count when the scroll closes the list again.
        await frame.evaluate(async (el, arrow) => {
          // Waits for what happened instead of for a guessed time: a slow runner takes longer for each step.
          const until = async (done: () => boolean) => {
            for (let i = 0; i < 200 && !done(); i++) await new Promise((resolve) => setTimeout(resolve, 5));
          };
          const listOpen = () => document.querySelector('[role="listbox"]') !== null;
          document.activeElement!.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }));
          await until(() => !listOpen());
          document.querySelector<HTMLElement>(arrow)!.click();
          await until(listOpen);
          el.scrollTop += 30;
        }, ARROW);
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
        await focusSearch(mode);
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
