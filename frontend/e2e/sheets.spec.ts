// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import type { Locator, Page } from "@playwright/test";
import { MAIN } from "./env";
import { expect, mainKey, signInWith, test } from "./fixtures";

// Seed data (creation order is fixed, see `backend/tests/e2e_app.py`).
const TYPE_48 = "avery-zweckform-l4736rev";
const TYPE_189 = "avery-zweckform-l4731rev"; // the edge sheet type: 189 cells
const FULL = "L4736-0002";
const DISCARDED = "L4736-0003";
const WAITING = "L4736-0004"; // full, its last two cells wait for confirmation
const EDGE = "L4731-0001"; // the 189-cell sheet, 120 cells used with purposes of 120 characters

/** API writes of the cleanup go with the admin key: the browser session's cookie needs the page's CSRF header. */
const KEY = () => ({ "X-Label-Hub-Key": mainKey() });
const noSideScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth);
/** The element is the one at the middle of its own box: it is on screen and nothing lies over it. */
const uncovered = (loc: Locator) =>
  loc.evaluate((el) => {
    const r = el.getBoundingClientRect();
    const at = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return at === el || el.contains(at);
  });
const setLanguage = (page: Page, lang: "de" | "en") => page.evaluate((l) => localStorage.setItem("lph.lang", l), lang);

/** Opens a react-aria select and takes the option whose name contains the text. */
async function choose(scope: Locator, select: RegExp, option: RegExp) {
  await scope.getByRole("button", { name: select }).click();
  await scope.page().getByRole("option", { name: option }).click();
}

/**
 * The sheet type field is a combobox: tap it, type the key (the one option then sits at the top), pick it. Playwright
 * would otherwise scroll the dialog or page to reach a far option, and a scroll of anything that contains the field
 * closes the (non-modal) list.
 */
async function chooseType(scope: Locator, field: RegExp, option: RegExp) {
  const box = scope.getByRole("combobox", { name: field });
  await box.click();
  // Select the shown label explicitly once the list is up, so the first character is typed over it (263-85).
  await expect(scope.page().getByRole("listbox")).toBeVisible();
  await scope.page().keyboard.press("ControlOrMeta+A");
  await scope.page().keyboard.type(option.source);
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

  // #253: the sheet section of the item view shows and edits the number of labels, and the preview plans exactly that many cells.
  test("set 5 labels on an item and see 5 planned cells", async () => {
    await setLanguage(page, "en");
    await page.setViewportSize({ width: 1280, height: 900 });
    const printers = (await (await page.request.get("/api/v1/printers")).json()) as Array<{ id: string; name: string }>;
    const printerId = printers.find((p) => p.name === "Office page printer")!.id;
    await page.goto("/");
    await page.evaluate((id) => localStorage.setItem("lph.printer", id), printerId);
    const usedBefore = async () => ((await (await page.request.get("/api/v1/sheets?state=active")).json()) as Array<{ used: number }>).map((s) => s.used);
    const before = await usedBefore();
    try {
      await page.goto("/lookup/grocy/7");
      const section = page.getByRole("region", { name: "Print onto a sheet" });
      const count = section.getByRole("spinbutton", { name: "Number of labels" });
      await expect(count).toHaveValue("1");
      await count.fill("5");
      // The Print panel's Copies field is the same number.
      await expect(page.getByRole("spinbutton", { name: "Copies" })).toHaveValue("5");
      const line = section.getByText(/^5 labels → cells [\d–, ]+ on L\d{4}-\d{4}$/);
      await expect(line).toBeVisible({ timeout: 30_000 });
      // "a–b" is a run, "a" a single cell: five cells in all.
      const spans = ((await line.textContent()) ?? "").replace(/^5 labels → cells /, "").replace(/ on .*$/, "").split(", ");
      const cells = spans.reduce((n, span) => {
        const [from, to] = span.split("–").map(Number);
        return n + (to === undefined ? 1 : to! - from! + 1);
      }, 0);
      expect(cells).toBe(5);
      await expect(section.getByRole("gridcell", { name: /, new/ })).toHaveCount(5);
      // A preview reserves nothing.
      expect(await usedBefore()).toEqual(before);

      // A phone, and a short screen as with the on-screen keyboard open: the field and the print button stay reachable.
      for (const size of [{ width: 390, height: 844 }, { width: 390, height: 400 }]) {
        await page.setViewportSize(size);
        await expect(count).toBeVisible();
        // Scrolled to the middle of the screen, as the browser does for the focused field when the keyboard opens:
        // nothing fixed (the tab bar) may lie over the field or over the print button.
        await count.evaluate((el) => el.scrollIntoView({ block: "center" }));
        expect(await uncovered(count)).toBe(true);
        const print = section.getByRole("button", { name: "Print onto sheet" });
        await print.evaluate((el) => el.scrollIntoView({ block: "center" }));
        expect(await uncovered(print)).toBe(true);
        expect(await noSideScroll(page)).toBe(true);
      }
    } finally {
      await page.evaluate(() => localStorage.removeItem("lph.printer"));
    }
  });

  // #350: 3490 has no usable margin, so its code goes on the back of the liner.
  test("a 3490 sheet gets its code on the back", async () => {
    await setLanguage(page, "en");
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.request.post(`${MAIN.url}/__e2e/tray-loading/reset`);
    await page.goto("/sheets");
    await page.getByRole("button", { name: "New sheet" }).click();
    const dialog = page.getByRole("dialog", { name: "Add a sheet" });
    await chooseType(dialog, /Sheet type/, /avery-zweckform-3490/);
    await choose(dialog, /Printer/, /Office page printer/);
    await expect(dialog.getByRole("radio", { name: /On the back of the liner/ })).toBeChecked();
    await dialog.getByRole("button", { name: "Continue" }).click();

    const steps = page.getByRole("dialog", { name: "Activate new sheet" });
    await expect(steps.getByRole("listitem").and(steps.locator('[aria-current="step"]'))).toContainText("Turn over");
    // The tray is not set up yet: the guided test comes first.
    await expect(steps.getByRole("button", { name: "Print sheet code" })).toBeDisabled();
    await steps.getByRole("button", { name: "Print test page" }).click();
    // React Aria's radio input is visually hidden: a person taps the label.
    await steps.getByRole("radiogroup", { name: "Is the print on the side with the cross?" }).getByText("Yes", { exact: true }).click();
    await steps.getByRole("radiogroup", { name: "Is “TOP” next to the cross?" }).getByText("Yes", { exact: true }).click();
    await steps.getByRole("button", { name: "Save for this tray" }).click();
    await expect(steps.getByText(/liner side up$/)).toBeVisible();
    await steps.getByRole("button", { name: "Print sheet code" }).click();

    await expect(steps.getByRole("heading", { name: "Did it print?" })).toBeVisible({ timeout: 20_000 });
    const code = /A3490-\d{4}/.exec((await steps.getByText(/sheet code A3490-\d{4}/).textContent())!)![0];
    // Newest first: the list defaults to the oldest jobs, and earlier specs of the run leave more than 20.
    const jobs = (await (await page.request.get("/api/v1/jobs?limit=20&order=newest", { headers: KEY() })).json()) as { payload: { kind?: string; detail?: { sheet_code?: string } } }[];
    expect(jobs.some((j) => j.payload.kind === "sheet_back_page" && j.payload.detail?.sheet_code === code)).toBe(true);
    await steps.getByRole("button", { name: "Yes, it is printed" }).click();
    await expect(steps).toHaveCount(0);

    await page.goto(`/sheets/${code}`);
    await expect(page.getByTestId("sheet-code-state")).toHaveText("On the back of the liner · printed");
    // Leave the hub as it was found: the tray unset, the sheet retired.
    await page.request.post(`${MAIN.url}/__e2e/tray-loading/reset`);
    expect((await page.request.post(`/api/v1/sheets/${code}/discard`, { headers: KEY() })).ok()).toBe(true);
  });

  // 1.7.0 acceptance: a printed margin sheet gets an extra code on the back; "Back side missing" until confirmed.
  test("a printed margin sheet gets a back side from the sheet code panel", async () => {
    await setLanguage(page, "en");
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.request.post(`${MAIN.url}/__e2e/tray-loading/reset`);
    // One label onto a new L4736 sheet: its page carries the margin code, so the code counts as printed.
    const items = [{ content_type: "text_two_lines", data: { title: "E2E panel", primary_id: "P-1" } }];
    const printed = await page.request.post("/api/v1/print/office-page/sheet", { data: { items, placements: [{ new_sheet: { type: TYPE_48 } }] }, headers: KEY() });
    expect(printed.ok()).toBe(true);
    const code = ((await printed.json()) as { pages: { sheet_code: string }[] }).pages[0]!.sheet_code;
    await expect
      .poll(async () => ((await (await page.request.get(`/api/v1/sheets/${code}`, { headers: KEY() })).json()) as { id_printed: boolean }).id_printed, { timeout: 20_000 })
      .toBe(true);

    await page.goto(`/sheets/${code}`);
    const panel = page.getByRole("region", { name: "Sheet code" });
    await expect(panel.getByTestId("sheet-code-state")).toHaveText("In the margin · printed");
    await expect(panel.getByTestId("sheet-code-back")).toHaveCount(0);
    await expect(panel.getByRole("button", { name: "Reprint margin code" })).toBeVisible();
    await panel.getByRole("button", { name: "Print back side" }).click();

    const steps = page.getByRole("dialog", { name: "Print back side" });
    await steps.getByRole("button", { name: "Print test page" }).click();
    await steps.getByRole("radiogroup", { name: "Is the print on the side with the cross?" }).getByText("Yes", { exact: true }).click();
    await steps.getByRole("radiogroup", { name: "Is “TOP” next to the cross?" }).getByText("Yes", { exact: true }).click();
    await steps.getByRole("button", { name: "Save for this tray" }).click();
    await steps.getByRole("button", { name: "Print sheet code" }).click();
    await expect(steps.getByRole("heading", { name: "Did it print?" })).toBeVisible({ timeout: 20_000 });
    // Left without confirming: the back side stays missing.
    await page.goto(`/sheets/${code}`);
    await expect(panel.getByTestId("sheet-code-state")).toHaveText("In the margin · printed");
    await expect(panel.getByTestId("sheet-code-back")).toContainText("missing");

    await page.goto("/sheets?back_missing=true");
    await expect(page.getByRole("link", { name: code })).toBeVisible();

    await page.goto(`/sheets/${code}`);
    await panel.getByRole("button", { name: "Yes, the back side is printed" }).click();
    await expect(panel.getByTestId("sheet-code-back")).toContainText("confirmed");
    await page.goto("/sheets?back_missing=true");
    await expect(page.getByRole("heading", { level: 1, name: "Sheets" })).toBeVisible();
    await expect(page.getByRole("link", { name: code })).toHaveCount(0);

    await page.request.post(`${MAIN.url}/__e2e/tray-loading/reset`);
    await expect
      .poll(async () => (await page.request.post(`/api/v1/sheets/${code}/discard`, { headers: KEY() })).status(), { timeout: 20_000 })
      .toBe(200);
  });

  test("a reserved cell is left out of a print", async () => {
    const type = "avery-zweckform-3490";
    const patch = (data: object) => page.request.patch(`/api/v1/sheet-types/${type}`, { data, headers: KEY() });
    await setLanguage(page, "en");
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto(`/sheets/archive?type=${type}`);
    await page.getByRole("tab", { name: "Where the code goes" }).click();
    await page.getByText("Reserved cell", { exact: true }).click();
    await choose(page.getByRole("tabpanel"), / Cell$/, /^2$/);
    await page.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Saved.")).toBeVisible();

    const items = [1, 2, 3].map((i) => ({ content_type: "text_two_lines", data: { title: `E2E ${i}`, primary_id: `R-${i}` } }));
    const printed = await page.request.post("/api/v1/print/office-page/sheet", { data: { items, placements: [{ new_sheet: { type } }] }, headers: KEY() });
    expect(printed.ok()).toBe(true);
    const [result] = ((await printed.json()) as { pages: { sheet_code: string; cells: number[]; id_cell: number | null }[] }).pages;
    expect(result!.id_cell).toBe(2);
    expect(result!.cells).toEqual([1, 3, 4]);
    await page.goto(`/sheets/${result!.sheet_code}`);
    await expect(page.getByRole("gridcell", { name: /^Cell 2,.*sheet code/ })).toBeVisible();

    expect((await patch({ id_placement: "auto", id_cell: null })).ok()).toBe(true);
    await expect
      .poll(async () => (await page.request.post(`/api/v1/sheets/${result!.sheet_code}/discard`, { headers: KEY() })).status(), { timeout: 20_000 })
      .toBe(200);
  });

  test("adds a sheet with three used cells, lists it with 45 free, and discards it again", async () => {
    await setLanguage(page, "en");
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/sheets");
    await page.getByRole("button", { name: "New sheet" }).click();
    const dialog = page.getByRole("dialog", { name: "Add a sheet" });
    await chooseType(dialog, /Sheet type/, new RegExp(TYPE_48));
    await expect(dialog.getByText(/It will probably become L4736-\d{4}\./)).toBeVisible();
    for (const n of [1, 2, 3]) await dialog.getByRole("gridcell", { name: new RegExp(`^Cell ${n},`) }).click();
    await expect(dialog.getByText("3 cells marked as used")).toBeVisible();
    await expect(dialog.getByRole("radio", { name: /In the margin/ })).toBeChecked();
    await dialog.getByRole("button", { name: "Add sheet" }).click();

    const added = dialog.getByRole("status").filter({ hasText: /^Sheet L4736-\d{4} was added\.$/ });
    await expect(added).toBeVisible();
    const code = /L4736-\d{4}/.exec((await added.textContent())!)![0];
    // The written Close button at the end, not the × in the corner (both are named Close).
    await dialog.getByRole("button", { name: "Close" }).filter({ hasText: "Close" }).click();

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
    await chooseType(dialog, /Sheet type/, new RegExp(TYPE_189));
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
    await chooseType(dialog, /Sheet type/, new RegExp(TYPE_189));
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
    await chooseType(dialog, /Sheet type/, new RegExp(TYPE_48));
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
    // Relative: print-sheet.spec.ts prints onto this sheet before this file runs.
    const used = ((await (await page.request.get("/api/v1/sheets/L4736-0001")).json()) as { used: number }).used;
    await page.goto("/sheets/L4736-0001");
    await expect(page.getByText(`${used} of 48 used`)).toBeVisible();
    await page.getByRole("button", { name: "Mark cells as used" }).click();
    await page.getByRole("gridcell", { name: /^Cell 48,/ }).click();
    await page.getByRole("textbox", { name: /^Purpose/ }).fill("e2e probe");
    await page.getByRole("button", { name: "Mark 1 cell as used" }).click();
    await expect(page.getByText(`${used + 1} of 48 used`)).toBeVisible();
    await expect(page.getByRole("list", { name: "Cells in use" })).toContainText("Cell 48 → e2e probe · marked by hand");

    await page.getByRole("button", { name: "Un-mark cells" }).click();
    await page.getByRole("gridcell", { name: /^Cell 48,/ }).click();
    await page.getByRole("button", { name: "Un-mark 1 cell" }).click();
    await expect(page.getByText(`${used} of 48 used`)).toBeVisible();
    await expect(page.getByRole("list", { name: "Cells in use" })).not.toContainText("e2e probe");
  });

  // This test leaves L4736-0004 resolved: there is no way to un-resolve cells, so no restore step. The sheet has its own
  // seeded copy for short-viewport.spec.ts. A retry after a late failure finds no unconfirmed cells and fails at the
  // first expectation; that only hides nothing, the first failure is the one to read.
  test("resolve all unconfirmed cells as printed", async () => {
    await setLanguage(page, "en");
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto(`/sheets/${WAITING}`);
    const section = page.getByRole("region", { name: "Unconfirmed cells" });
    await expect(section).toBeVisible();
    await expect(section.getByRole("listitem")).toHaveCount(2);
    await section.getByRole("button", { name: "Resolve all as printed" }).click();
    const dialog = page.getByRole("alertdialog", { name: "Resolve 2 cells as printed?" });
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "Resolve as printed" }).click();
    await expect(dialog).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Unconfirmed cells" })).toHaveCount(0);
    await expect(page.getByText("48 of 48 used")).toBeVisible();
  });

  test("sheet filter switches stay tappable on a narrow tablet", async ({ browser }) => {
    // A portrait tablet with larger text: the content column is narrow, and the old five-column filter row let the
    // code search and the type combobox paint over the switch tracks (a tap then landed in the combobox).
    const context = await browser.newContext({
      baseURL: MAIN.url,
      viewport: { width: 1232, height: 1970 },
      hasTouch: true,
      isMobile: true,
      storageState: await page.context().storageState(),
    });
    try {
      const tablet = await context.newPage();
      await tablet.addInitScript(() => localStorage.setItem("lph.lang", "en"));
      await tablet.goto("/sheets");
      await expect(tablet.getByRole("heading", { level: 1, name: "Sheets" })).toBeVisible();
      await tablet.evaluate(() => {
        document.documentElement.style.zoom = "1.5";
      });
      for (const name of ["Hide used-up sheets", "Show discarded sheets", "Back side missing"]) {
        const input = tablet.getByRole("switch", { name });
        const label = tablet.locator("label").filter({ has: input });
        const track = label.locator("span[aria-hidden='true']").first();
        await track.scrollIntoViewIfNeeded();
        // Measured in the page, in the same coordinate space `elementFromPoint` and a tap use (the zoom skews `boundingBox`).
        // Three points along the track: the left end is where a wide neighbour reaches first.
        const { x, y, insideLabel } = await track.evaluate((el, text) => {
          const r = el.getBoundingClientRect();
          const py = r.top + r.height / 2;
          const xs = [r.left + 6, r.left + r.width / 2, r.right - 6];
          const inside = xs.every((px) => {
            const owner = document.elementFromPoint(px, py)?.closest("label");
            return !!owner && (owner.textContent ?? "").includes(text);
          });
          return { x: xs[1]!, y: py, insideLabel: inside };
        }, name);
        expect(insideLabel, `${name}: the point on its track belongs to its own label`).toBe(true);
        const before = await input.isChecked();
        await tablet.touchscreen.tap(x, y);
        await expect.poll(() => input.isChecked(), { message: `${name} toggles on tap` }).toBe(!before);
      }
    } finally {
      await context.close();
    }
  });

  test("the sheet filter controls do not overlap at 1440 px", async () => {
    await setLanguage(page, "en");
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/sheets");
    await expect(page.getByRole("heading", { level: 1, name: "Sheets" })).toBeVisible();
    const boxes = await page.evaluate(() => {
      const form = document.querySelector("#sheet-filters");
      if (!form) return [];
      const controls = [
        form.querySelector("input[type='text'], input:not([role])"),
        form.querySelector("[role='combobox']"),
        ...Array.from(form.querySelectorAll("label")),
      ];
      return controls.filter(Boolean).map((el) => {
        const r = (el as Element).getBoundingClientRect();
        return { left: r.left, right: r.right, top: r.top, bottom: r.bottom };
      });
    });
    expect(boxes.length).toBeGreaterThanOrEqual(5);
    for (let i = 0; i < boxes.length; i++) {
      for (let j = i + 1; j < boxes.length; j++) {
        const a = boxes[i]!;
        const b = boxes[j]!;
        const apart = a.right <= b.left + 1 || b.right <= a.left + 1 || a.bottom <= b.top + 1 || b.bottom <= a.top + 1;
        expect(apart, `filter controls ${i} and ${j} do not intersect`).toBe(true);
      }
    }
  });

  test("says that a discarded sheet is discarded, and that an unknown code does not exist", async () => {
    await setLanguage(page, "en");
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto(`/sheets/${DISCARDED}`);
    await expect(page.getByText(/^Discarded on .+, this code is not used again\.$/)).toBeVisible();
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
        // By name: a Select list closed while it still fades in stays in the DOM until its animation ends,
        // and it is a dialog too (React Aria popover).
        const dialog = page.getByRole("dialog", { name: de ? "Bogen hinzufügen" : "Add a sheet" });
        await expect(dialog).toBeVisible();
        await chooseType(dialog, de ? /Bogentyp/ : /Sheet type/, new RegExp(TYPE_48));
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
