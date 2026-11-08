import type { Locator, Page } from "@playwright/test";
import { MAIN } from "./env";
import { expect, mainKey, signInWith, test } from "./fixtures";

// Seed data (creation order is fixed, see `backend/tests/e2e_app.py`).
const TYPE_48 = "avery-zweckform-l4736rev";
const TYPE_189 = "avery-zweckform-l4731rev"; // the edge sheet type: 189 cells
const FULL = "L4736-0002";
const DISCARDED = "L4736-0003";

const noSideScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth);
const setLanguage = (page: Page, lang: "de" | "en") => page.evaluate((l) => localStorage.setItem("lph.lang", l), lang);

/** Opens a react-aria select and takes the option whose name contains the text. */
async function choose(scope: Locator, select: RegExp, option: RegExp) {
  await scope.getByRole("button", { name: select }).click();
  await scope.page().getByRole("option", { name: option }).click();
}

// One sign-in for the whole file: the hub limits sign-ins per minute.
test.describe.serial("sheets", () => {
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

  test("hides the used-up sheet by default and shows it, marked, on request", async () => {
    await setLanguage(page, "en");
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/sheets");
    await expect(page.getByRole("heading", { level: 1, name: "Sheets" })).toBeVisible();
    await expect(page.getByRole("link", { name: "L4736-0001" })).toBeVisible();
    await expect(page.getByRole("link", { name: FULL })).toHaveCount(0);
    await expect(page.getByRole("link", { name: DISCARDED })).toHaveCount(0);

    // A switch is clicked on its label: the input itself sits under the track.
    // The hint under the list has a button; its tap target is a real 44 px (an inline box would not be).
    const showThem = page.getByRole("button", { name: "Show them" });
    await expect(showThem).toBeVisible();
    expect((await showThem.boundingBox())!.height).toBeGreaterThanOrEqual(43.99);
    await page.getByText("Hide used-up sheets", { exact: true }).click();
    const full = page.getByRole("row").filter({ has: page.getByRole("link", { name: FULL }) });
    await expect(full).toContainText("used up");
    await expect(full.getByRole("button", { name: /Discard/ })).toBeVisible();

    await page.getByText("Show discarded sheets", { exact: true }).click();
    const gone = page.getByRole("row").filter({ has: page.getByRole("link", { name: DISCARDED }) });
    await expect(gone).toContainText("discarded");
    await expect(gone.getByRole("button", { name: /Discard/ })).toHaveCount(0);
  });

  test("adds a sheet with three used cells, lists it with 45 free, and discards it again", async () => {
    await setLanguage(page, "en");
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/sheets");
    await page.getByRole("button", { name: "New sheet" }).click();
    const dialog = page.getByRole("dialog", { name: "Add a sheet" });
    await choose(dialog, /Sheet type/, new RegExp(TYPE_48));
    await expect(dialog.getByText(/It will probably become L4736-\d{4}\./)).toBeVisible();
    for (const n of [1, 2, 3]) await dialog.getByRole("gridcell", { name: new RegExp(`^Cell ${n},`) }).click();
    await expect(dialog.getByText("3 cells marked as used")).toBeVisible();
    await expect(dialog.getByRole("radio", { name: /In the margin/ })).toBeChecked();
    await dialog.getByRole("button", { name: "Add sheet" }).click();

    const added = dialog.getByRole("status").filter({ hasText: /^Sheet L4736-\d{4} was added\.$/ });
    await expect(added).toBeVisible();
    const code = /L4736-\d{4}/.exec((await added.textContent())!)![0];
    await dialog.getByRole("button", { name: "Close" }).click();

    const row = page.getByRole("row").filter({ has: page.getByRole("link", { name: code }) });
    await expect(row).toContainText("3 of 48 used");
    await expect(row).toContainText("45 free");

    // The question names what a discard does; the sheet then leaves the list.
    await row.getByRole("button", { name: `Discard ${code}` }).click();
    const confirm = page.getByRole("alertdialog");
    await expect(confirm).toContainText("its number is never given out again");
    await confirm.getByRole("button", { name: "Discard sheet" }).click();
    await expect(page.getByRole("link", { name: code })).toHaveCount(0);
  });

  test("the add dialog with the 189-cell edge sheet keeps 44 px tap targets and no side scroll at 360 px", async () => {
    await setLanguage(page, "en");
    await page.setViewportSize({ width: 360, height: 780 });
    await page.goto("/sheets");
    await page.getByRole("button", { name: "New sheet" }).click();
    const dialog = page.getByRole("dialog", { name: "Add a sheet" });
    await choose(dialog, /Sheet type/, new RegExp(TYPE_189));
    const cells = dialog.getByRole("gridcell");
    await expect(cells).toHaveCount(189);

    // The touch target of a cell is its pitch box (`data-hit`): the label plus half the gap each side.
    const smallest = await dialog.locator("[role=gridcell] rect[data-hit]").evaluateAll((rects) =>
      Math.min(...rects.flatMap((r) => {
        const box = r.getBoundingClientRect();
        return [box.width, box.height];
      })),
    );
    expect(smallest).toBeGreaterThanOrEqual(43.99);
    // The grid opens at its leading edge: the first column is the first thing seen, not scrolled out of sight.
    const lead = await dialog.locator("[data-scroll]").evaluate((scroller) => {
      const box = scroller.getBoundingClientRect();
      const first = scroller.querySelector("[data-cell='1'] rect[data-hit]")!.getBoundingClientRect();
      return { scrollLeft: scroller.scrollLeft, gap: first.left - box.left };
    });
    expect(lead.scrollLeft).toBe(0);
    expect(lead.gap).toBeGreaterThanOrEqual(-0.5);
    expect(await noSideScroll(page)).toBe(true);
  });

  for (const [lang, size] of [
    ["de", { width: 360, height: 780 }],
    ["en", { width: 1280, height: 800 }],
  ] as const) {
    for (const scheme of ["light", "dark"] as const) {
      test(`layout and screenshots, ${lang} at ${size.width} px, ${scheme}`, async () => {
        const testInfo = test.info();
        const de = lang === "de";
        await setLanguage(page, lang);
        await page.emulateMedia({ colorScheme: scheme });
        await page.setViewportSize(size);
        const shot = (name: string) => page.screenshot({ path: testInfo.outputPath(`${name}-${size.width}-${lang}-${scheme}.png`), fullPage: true });

        await page.goto("/sheets?full=true&discarded=true");
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
        await expect(page.getByRole("link", { name: "L4731-0001" })).toBeVisible();
        expect(await noSideScroll(page)).toBe(true);
        await shot("list");

        await page.getByRole("button", { name: de ? "Neuer Bogen" : "New sheet" }).click();
        const dialog = page.getByRole("dialog");
        await expect(dialog).toBeVisible();
        await choose(dialog, de ? /Bogentyp/ : /Sheet type/, new RegExp(TYPE_48));
        for (const n of [1, 2, 3, 4]) await dialog.getByRole("gridcell", { name: new RegExp(`^(Cell|Zelle) ${n},`) }).click();
        await choose(dialog, de ? /Drucker/ : /Printer/, /Office page printer/);
        await expect(dialog.getByRole("status").filter({ hasText: /margin|Rand|add it by hand|von Hand/ }).first()).toBeVisible();
        expect(await noSideScroll(page)).toBe(true);
        // The dialog scrolls inside itself, so its top and its bottom are two pictures of the viewport.
        const scrollDialog = (to: "top" | "bottom") =>
          dialog.evaluate((el, where) => {
            let box: HTMLElement | null = el.parentElement;
            while (box && getComputedStyle(box).overflowY !== "auto") box = box.parentElement;
            if (box) box.scrollTop = where === "top" ? 0 : box.scrollHeight;
          }, to);
        const viewportShot = (name: string) => page.screenshot({ path: testInfo.outputPath(`${name}-${size.width}-${lang}-${scheme}.png`) });
        await scrollDialog("top");
        await viewportShot("dialog-top");
        await scrollDialog("bottom");
        await expect(dialog.getByRole("button", { name: de ? "Bogen hinzufügen" : "Add sheet" })).toBeInViewport();
        await viewportShot("dialog-bottom");
        await page.keyboard.press("Escape");
        await page.emulateMedia({ colorScheme: "light" });
      });
    }
  }
});
