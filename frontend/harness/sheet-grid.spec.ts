import { expect, test, type Page } from "@playwright/test";

// Real-browser layout checks that jsdom cannot make (preflight C3): the tap target size, the absence
// of page-level horizontal scroll, and the focus ring. Screenshots are test artifacts (`testInfo.outputPath`).
const PHONE = { width: 360, height: 780 };
const DESKTOP = { width: 1280, height: 800 };

const open = async (page: Page, query: string) => {
  await page.goto(`/harness/sheet-grid.html?${query}`);
  await expect(page.getByRole("grid")).toBeVisible();
};
const noPageOverflow = (page: Page) =>
  page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
const hitBoxes = (page: Page) =>
  page.evaluate(() =>
    [...document.querySelectorAll('[data-hit="1"]')].map((el) => {
      const r = el.getBoundingClientRect();
      return { w: r.width, h: r.height };
    }),
  );

test.describe("SheetGrid in a real browser", () => {
  test("view fits a 360 px phone: no sideways page scroll, pitch boxes about 44 px wide (43+ with the page padding)", async ({ page }, testInfo) => {
    await page.setViewportSize(PHONE);
    await open(page, "type=l4731&mode=view");
    expect(await noPageOverflow(page)).toBe(true);
    const svgWidth = await page.locator('svg[role="grid"]').evaluate((el) => el.getBoundingClientRect().width);
    expect(svgWidth).toBeLessThanOrEqual(360);
    const boxes = await hitBoxes(page);
    expect(boxes).toHaveLength(189);
    // The harness page pads 16 px a side, so the container is 328 px: 27.9 mm x 328/210 = 43.6 px. View is for
    // reading; tapping uses the zoomed tap view below, which is held to the full 44 px.
    for (const b of boxes) expect(b.w).toBeGreaterThanOrEqual(43);
    await page.screenshot({ path: testInfo.outputPath("view-360-l4731-en.png"), fullPage: true });
  });

  for (const type of ["l4731", "l4736", "round"]) {
    test(`select at 360 px, ${type}: every hit box is 44 x 44 px, the scroller (not the page) overflows`, async ({ page }, testInfo) => {
      await page.setViewportSize(PHONE);
      await open(page, `type=${type}&mode=select`);
      expect(await noPageOverflow(page)).toBe(true);
      for (const b of await hitBoxes(page)) {
        expect(b.w).toBeGreaterThanOrEqual(43.99);
        expect(b.h).toBeGreaterThanOrEqual(43.99);
      }
      const scroller = page.locator('[data-scroll="both"]');
      const sizes = await scroller.evaluate((el) => ({ sw: el.scrollWidth, cw: el.clientWidth, sh: el.scrollHeight, ch: el.clientHeight }));
      // Types whose cells are already 44 px at the fitted size (round, 36 mm pitch) need no sideways scroll.
      if (type !== "round") {
        expect(sizes.sw).toBeGreaterThan(sizes.cw);
        expect(sizes.sh).toBeGreaterThan(sizes.ch);
      }
      await page.screenshot({ path: testInfo.outputPath(`select-360-${type}-en.png`) });
    });
  }

  test("a tap on a free cell selects it, a tap on a used cell does nothing", async ({ page }) => {
    await page.setViewportSize(PHONE);
    await open(page, "type=l4731&mode=select");
    const cell = (n: number) => page.getByRole("gridcell", { name: new RegExp(`^Cell ${n},`) });
    await cell(130).scrollIntoViewIfNeeded();
    await expect(cell(130)).toHaveAccessibleName("Cell 130, free");
    await cell(130).click();
    await expect(cell(130)).toHaveAccessibleName("Cell 130, new");
    await cell(2).scrollIntoViewIfNeeded();
    await cell(2).click({ force: true });
    await expect(cell(2)).toHaveAccessibleName(/^Cell 2, used,/);
  });

  test("keyboard focus shows a visible ring on the focused cell only", async ({ page }, testInfo) => {
    await page.setViewportSize(DESKTOP);
    await open(page, "type=l4736&mode=select");
    await page.keyboard.press("Tab"); // legend has no stops; the grid's single tab stop is next
    const focused = page.locator('[role="gridcell"]:focus');
    await expect(focused).toHaveCount(1);
    await page.keyboard.press("ArrowRight");
    await expect(page.locator('[role="gridcell"]:focus')).toHaveAccessibleName(/^Cell 2,/);
    const stroke = await page.locator('[role="gridcell"]:focus').locator('[data-ring="1"]').evaluate((el) => getComputedStyle(el).stroke);
    expect(stroke).not.toBe("rgba(0, 0, 0, 0)");
    expect(stroke).not.toBe("none");
    await page.screenshot({ path: testInfo.outputPath("focus-1280-l4736-en.png") });
  });

  test("desktop view stays at a reading size", async ({ page }, testInfo) => {
    await page.setViewportSize(DESKTOP);
    await open(page, "type=l4731&mode=view");
    const w = await page.locator('svg[role="grid"]').evaluate((el) => el.getBoundingClientRect().width);
    expect(w).toBeLessThanOrEqual(760);
    await page.screenshot({ path: testInfo.outputPath("view-1280-l4731-en.png"), fullPage: true });
  });

  test("German copy, the unknown radius and the legend", async ({ page }, testInfo) => {
    await page.setViewportSize(PHONE);
    await open(page, "type=l4736&mode=view&lang=de");
    await expect(page.getByText("unbekannt")).toBeVisible();
    await expect(page.getByRole("list").getByText("belegt")).toBeVisible();
    expect(await noPageOverflow(page)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath("view-360-l4736-de.png"), fullPage: true });
  });

  test("a 1 x 7 lever-arch type fits the phone", async ({ page }, testInfo) => {
    await page.setViewportSize(PHONE);
    await open(page, "type=lever&mode=view");
    expect(await noPageOverflow(page)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath("view-360-lever-en.png"), fullPage: true });
  });

  test("the page image stays readable under the cells", async ({ page }, testInfo) => {
    await page.setViewportSize(DESKTOP);
    await open(page, "type=l4736&mode=view&overlay=1");
    // the grid draws no opaque fill over the image: every cell shape is transparent
    const fills = await page.locator('svg[role="grid"] [data-shape="cell"]').evaluateAll((els) => els.map((el) => getComputedStyle(el).fill));
    expect(fills.length).toBe(48);
    for (const fill of fills) expect(fill).toMatch(/^(none|rgba\(0, 0, 0, 0\)|transparent)$/);
    await page.screenshot({ path: testInfo.outputPath("overlay-1280-l4736-en.png") });
  });
});
