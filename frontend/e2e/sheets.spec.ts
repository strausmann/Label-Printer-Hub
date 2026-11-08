import type { Locator, Page } from "@playwright/test";
import { MAIN } from "./env";
import { expect, mainKey, signInWith, test } from "./fixtures";

// Seed data (creation order is fixed, see `backend/tests/e2e_app.py`).
const TYPE_48 = "avery-zweckform-l4736rev";
const TYPE_189 = "avery-zweckform-l4731rev"; // the edge sheet type: 189 cells
const FULL = "L4736-0002";
const DISCARDED = "L4736-0003";
const EDGE = "L4731-0001"; // the 189-cell sheet, 120 cells used with purposes of 120 characters

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

    // The hint under the list has a button; its tap target is a real 44 px (an inline box would not be).
    const showThem = page.getByRole("button", { name: "Show them" });
    await expect(showThem).toBeVisible();
    expect((await showThem.boundingBox())!.height).toBeGreaterThanOrEqual(43.99);
    // A switch is clicked on its label: the input itself sits under the track.
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

  test("tapping a half-visible cell on the 189-cell sheet at 360 px does not move the pan view, and a new type starts at the edge", async () => {
    await setLanguage(page, "en");
    await page.setViewportSize({ width: 360, height: 780 });
    await page.goto("/sheets");
    await page.getByRole("button", { name: "New sheet" }).click();
    const dialog = page.getByRole("dialog", { name: "Add a sheet" });
    await choose(dialog, /Sheet type/, new RegExp(TYPE_189));
    await expect(dialog.getByRole("gridcell")).toHaveCount(189);
    const scroller = dialog.locator("[data-scroll]");
    const view = () =>
      scroller.evaluate((el) => {
        const box = el.getBoundingClientRect();
        const rect = (n: number) => el.querySelector(`[data-cell='${n}'] rect[data-hit]`)!.getBoundingClientRect();
        return { scrollLeft: el.scrollLeft, left: box.left, right: box.right, c1: rect(1).left, c3: rect(3) };
      });

    // At the leading edge cells 1 and 2 fit; cell 3 only peeks in at the right edge. A finger can only hit the part that shows.
    let v = await view();
    expect(v.c3.left).toBeLessThan(v.right - 8);
    expect(v.c3.right).toBeGreaterThan(v.right + 5);
    await page.mouse.click((v.c3.left + v.right) / 2, v.c3.top + v.c3.height / 2);
    await expect(dialog.getByRole("gridcell", { name: /^Cell 3, used/ })).toBeVisible();
    v = await view();
    expect(v.scrollLeft).toBe(0);
    expect(v.c1).toBeGreaterThanOrEqual(v.left - 0.5);

    // Panned somewhere and then another type chosen: the new grid starts at its leading edge, not at the old offset.
    await scroller.evaluate((el) => (el.scrollLeft = 200));
    await choose(dialog, /Sheet type/, new RegExp(TYPE_48));
    await expect(dialog.getByRole("gridcell")).toHaveCount(48);
    expect((await view()).scrollLeft).toBe(0);
  });

  test("the page of a sheet opened by its address (the scanned URL) lists what is in its cells", async () => {
    await setLanguage(page, "en");
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/sheet/L4736-0001");
    await expect(page.getByRole("heading", { level: 1, name: "L4736-0001" })).toBeVisible();
    const list = page.getByRole("list", { name: "Cells in use" });
    await expect(list).toContainText("Cell 1 → item 1 · marked by hand");
    await expect(list).toContainText("Cell 17 → item 17 · marked by hand");
    await expect(page.getByRole("link", { name: "Print onto this sheet" })).toHaveAttribute("href", "/cart?sheet=L4736-0001");
    // The purpose is read on a tap, not only on hover.
    await page.getByRole("gridcell", { name: /^Cell 4,/ }).click();
    await expect(page.getByRole("status", { name: "Selected cell" })).toContainText("Cell 4 → item 4 · marked by hand");
  });

  test("marks a cell by hand and takes the mark back again (net zero for the other specs)", async () => {
    await setLanguage(page, "en");
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/sheets/L4736-0001");
    await expect(page.getByText("17 of 48 used")).toBeVisible();
    await page.getByRole("button", { name: "Mark cells as used" }).click();
    await page.getByRole("gridcell", { name: /^Cell 48,/ }).click();
    await page.getByRole("textbox", { name: /^Purpose/ }).fill("e2e probe");
    await page.getByRole("button", { name: "Mark 1 cell as used" }).click();
    await expect(page.getByText("18 of 48 used")).toBeVisible();
    await expect(page.getByRole("list", { name: "Cells in use" })).toContainText("Cell 48 → e2e probe · marked by hand");

    await page.getByRole("button", { name: "Un-mark cells" }).click();
    await page.getByRole("gridcell", { name: /^Cell 48,/ }).click();
    await page.getByRole("button", { name: "Un-mark 1 cell" }).click();
    await expect(page.getByText("17 of 48 used")).toBeVisible();
    await expect(page.getByRole("list", { name: "Cells in use" })).not.toContainText("e2e probe");
  });

  test("says that a discarded sheet is discarded, and that an unknown code does not exist", async () => {
    await setLanguage(page, "en");
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto(`/sheets/${DISCARDED}`);
    await expect(page.getByText(/^Discarded on .+, this ID is not used again\.$/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Mark cells as used" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Discard sheet" })).toHaveCount(0);
    await page.goto("/sheet/L4736-9999");
    await expect(page.getByText("That sheet does not exist.")).toBeVisible();
    await expect(page.getByRole("link", { name: "Back to the sheets" })).toBeVisible();
  });

  test("at 360 px the 48-cell sheet is an overview in view mode and a 44 px grid only while choosing", async () => {
    await setLanguage(page, "en");
    await page.setViewportSize({ width: 360, height: 780 });
    await page.goto("/sheets/L4736-0001");
    const grid = page.getByRole("grid", { name: "L4736-0001" });
    await expect(grid.getByRole("gridcell")).toHaveCount(48);
    // View: the whole page fits the width, all 4 columns are on screen, nothing pans.
    expect(await page.locator("[data-scroll]").count()).toBe(0);
    const columns = await grid.evaluate((svg) => {
      const view = document.documentElement.clientWidth;
      return [1, 2, 3, 4].map((n) => {
        const box = svg.querySelector(`[data-cell='${n}'] rect[data-shape]`)!.getBoundingClientRect();
        return box.left >= 0 && box.right <= view + 0.5;
      });
    });
    expect(columns).toEqual([true, true, true, true]);
    expect(await noSideScroll(page)).toBe(true);

    // Choosing: zoomed and scrollable, every cell at least 44 x 44 px.
    await page.getByRole("button", { name: "Mark cells as used" }).click();
    await expect(page.locator("[data-scroll]")).toHaveCount(1);
    const smallest = await page.locator("[role=gridcell] rect[data-hit]").evaluateAll((rects) =>
      Math.min(...rects.flatMap((r) => {
        const box = r.getBoundingClientRect();
        return [box.width, box.height];
      })),
    );
    expect(smallest).toBeGreaterThanOrEqual(43.99);
    expect(await noSideScroll(page)).toBe(true);
    await page.getByRole("button", { name: "Cancel" }).click();
  });

  test("the 189-cell sheet at 360 px: overview in view mode, 44 px cells while choosing, long purposes wrap, no side scroll", async () => {
    await setLanguage(page, "en");
    await page.setViewportSize({ width: 360, height: 780 });
    await page.goto(`/sheets/${EDGE}`);
    await expect(page.getByRole("gridcell")).toHaveCount(189);
    expect(await noSideScroll(page)).toBe(true);
    // A purpose of 120 characters is readable in full on a tap and does not push the page wider.
    await page.getByRole("gridcell", { name: /^Cell 7,/ }).click();
    const status = page.getByRole("status", { name: "Selected cell" });
    await expect(status).toContainText("cell 007 ");
    expect(await status.evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
    expect(await noSideScroll(page)).toBe(true);

    // Choosing zooms: every touch target is at least 44 px, inside its own scroll container.
    await page.getByRole("button", { name: "Mark cells as used" }).click();
    const smallest = await page.locator("[role=gridcell] rect[data-hit]").evaluateAll((rects) =>
      Math.min(...rects.flatMap((r) => {
        const box = r.getBoundingClientRect();
        return [box.width, box.height];
      })),
    );
    expect(smallest).toBeGreaterThanOrEqual(43.99);
    expect(await noSideScroll(page)).toBe(true);
    await page.getByRole("button", { name: "Cancel" }).click();
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

  for (const [lang, size] of [
    ["de", { width: 360, height: 780 }],
    ["en", { width: 1280, height: 800 }],
  ] as const) {
    for (const scheme of ["light", "dark"] as const) {
      test(`detail layout and screenshots, ${lang} at ${size.width} px, ${scheme}`, async () => {
        const testInfo = test.info();
        const de = lang === "de";
        await setLanguage(page, lang);
        await page.emulateMedia({ colorScheme: scheme });
        await page.setViewportSize(size);
        const shot = (name: string) => page.screenshot({ path: testInfo.outputPath(`${name}-${size.width}-${lang}-${scheme}.png`), fullPage: true });

        for (const [name, code] of [["detail", "L4736-0001"], ["detail-discarded", DISCARDED], ["detail-edge", EDGE], ["detail-full", FULL]] as const) {
          await page.goto(`/sheets/${code}`);
          await expect(page.getByRole("heading", { level: 1, name: code })).toBeVisible();
          await expect(page.getByRole("grid")).toBeVisible();
          expect(await noSideScroll(page)).toBe(true);
          await shot(name);
        }
        await page.goto("/sheets/L4736-0001");
        await page.getByRole("button", { name: de ? "Zellen als belegt markieren" : "Mark cells as used" }).click();
        for (const n of [30, 31]) await page.getByRole("gridcell", { name: new RegExp(`^(Cell|Zelle) ${n},`) }).click();
        await expect(page.getByRole("heading", { level: 2, name: de ? "Zellen als belegt markieren" : "Mark cells as used" })).toBeVisible();
        expect(await noSideScroll(page)).toBe(true);
        await shot("detail-marking");
        await page.goto("/sheet/L4736-9999");
        await expect(page.getByRole("link", { name: de ? "Zurück zu den Bögen" : "Back to the sheets" })).toBeVisible();
        await shot("detail-unknown");
        await page.emulateMedia({ colorScheme: "light" });
      });
    }
  }
});
