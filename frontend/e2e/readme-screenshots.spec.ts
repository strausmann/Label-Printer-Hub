import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test";
import { SHOTS } from "./env";
import { signInWith } from "./fixtures";

/**
 * Renders the screenshots of the README into `docs/screenshots/` (run by `pnpm screenshots`, never by `pnpm e2e`).
 *
 * The views, in the order the README shows them, and the website shot each one maps to (the rename to Labelyard
 * writes `website/src/assets/screens/<shot>.<en|de>.<light|dark>.webp`):
 *
 *   overview        hero
 *   printers        printers
 *   printer-detail  printer-detail
 *   jobs            jobs
 *   sheets          sheets
 *   sheet-archive   sheet-archive
 *   calibration     calibration
 *   print-dialog    print-dialog
 *   cart-sheet      cart-sheet
 *
 * Desktop is 1440 x 900 in light and dark for every view; the phone (390 x 844) shows `overview`, `printer-detail`
 * and `sheets`. File names are `<view>-<light|dark>[-phone].png`.
 *
 * Why two runs give the same bytes: the hub is the e2e app on its fixtures, and every seeded job and sheet carries
 * `FIXTURE_TIME` (`E2E_FIXTURE_TIME`, see `backend/tests/e2e_app.py`); the browser clock is fixed (`CLOCK`), its
 * locale and time zone are pinned, motion is off, the fonts are the bundled ones and the device scale factor is 1.
 */
const OUT = resolve(import.meta.dirname, "..", "..", "docs", "screenshots");
const CLOCK = new Date("2026-11-01T09:00:00Z");
const KEY = () => readFileSync(SHOTS.keyFile, "utf8").trim();

type Scheme = "light" | "dark";
type Size = { name: "" | "-phone"; width: number; height: number };
const DESKTOP: Size = { name: "", width: 1440, height: 900 };
const PHONE: Size = { name: "-phone", width: 390, height: 844 };

type View = { name: string; phone: boolean; open: (page: Page) => Promise<void> };

const id = async (page: Page, printer: string) => {
  const printers = (await (await page.request.get("/api/v1/printers")).json()) as Array<{ id: string; name: string }>;
  return printers.find((p) => p.name === printer)!.id;
};

/** Waits until the shell shows the live connection and the web fonts are in, so nothing changes under the camera. */
async function settle(page: Page) {
  await expect(page.getByText(/^Connected/)).toBeAttached(); // hidden on the phone layout
  await page.evaluate(() => document.fonts.ready);
  // Park the pointer on nothing: a hover state would depend on when the browser last updated it.
  await page.mouse.move(0, 0);
}

/** A cart of Grocy labels and the page printer as the chosen one: what the print-onto-sheet page needs. */
async function fillCart(page: Page) {
  const printer = await id(page, "Office page printer");
  await page.evaluate((p) => {
    localStorage.setItem("lph.printer", p);
    const line = (n: string, copies: number) => ({ app: "grocy", id: n, name: "Flour", content_type: "qr_two_lines", copies });
    localStorage.setItem("lph.cart", JSON.stringify([line("7", 6), line("8", 3)]));
  }, printer);
}

const VIEWS: View[] = [
  {
    name: "overview",
    phone: true,
    open: async (page) => {
      await page.goto("/");
      await expect(page.getByRole("heading", { level: 1, name: "Overview" })).toBeVisible();
      await expect(page.getByText("12 mm").first()).toBeVisible();
    },
  },
  {
    name: "printers",
    phone: false,
    open: async (page) => {
      await page.goto("/printers");
      await expect(page.getByRole("link", { name: /Bench PT-P750W/ })).toBeVisible();
      await expect(page.getByText("12 mm").first()).toBeVisible();
    },
  },
  {
    name: "printer-detail",
    phone: true,
    open: async (page) => {
      await page.goto(`/printers/${await id(page, "Bench PT-P750W")}`);
      await expect(page.getByRole("heading", { level: 1, name: "Bench PT-P750W" })).toBeVisible();
      await expect(page.getByText("12 mm").first()).toBeVisible();
      // The roll prompt first says "Loading...", then offers the colours: wait for the second state.
      await expect(page.getByRole("button", { name: "Skip" })).toBeVisible();
    },
  },
  {
    name: "jobs",
    phone: false,
    open: async (page) => {
      await page.goto("/jobs");
      await expect(page.getByRole("link", { name: "Failed cable label" })).toBeVisible();
    },
  },
  {
    name: "sheets",
    phone: true,
    open: async (page) => {
      await page.goto("/sheets");
      await expect(page.getByRole("link", { name: "L4736-0001" })).toBeVisible();
    },
  },
  {
    name: "sheet-archive",
    phone: false,
    open: async (page) => {
      await page.goto("/sheets/archive");
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    },
  },
  {
    name: "calibration",
    phone: false,
    open: async (page) => {
      await page.goto(`/calibration?printer=${await id(page, "Office page printer")}&tray=main-tray`);
      await expect(page.getByRole("heading", { level: 1, name: "Calibration" })).toBeVisible();
      await expect(page.getByRole("img", { name: /^Calibration page of / })).toBeVisible();
    },
  },
  {
    name: "print-dialog",
    phone: false,
    open: async (page) => {
      await page.goto("/asset/42");
      await expect(page.getByRole("heading", { level: 1, name: "Snipe-IT item" })).toBeVisible();
      const preview = page.getByRole("img", { name: "Label preview" });
      await expect(preview).toBeVisible();
      await expect.poll(() => preview.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0)).toBe(true);
    },
  },
  {
    name: "cart-sheet",
    phone: false,
    open: async (page) => {
      await page.goto("/");
      await fillCart(page);
      await page.goto("/cart?sheet=L4736-0001");
      await expect(page.getByRole("heading", { level: 2, name: "Print onto a sheet" })).toBeVisible();
      await expect(page.getByRole("button", { name: "Print onto sheet" })).toBeEnabled({ timeout: 30_000 });
    },
  },
];

async function newContext(browser: Browser, scheme: Scheme, size: Size): Promise<BrowserContext> {
  const context = await browser.newContext({
    baseURL: SHOTS.url,
    viewport: { width: size.width, height: size.height },
    deviceScaleFactor: 1,
    colorScheme: scheme,
    reducedMotion: "reduce",
    locale: "en-US",
    timezoneId: "UTC",
  });
  await context.clock.install({ time: CLOCK });
  return context;
}

for (const scheme of ["light", "dark"] as const) {
  for (const size of [DESKTOP, PHONE]) {
    test(`README screenshots, ${scheme}${size.name}`, async ({ browser }) => {
      test.setTimeout(180_000);
      const context = await newContext(browser, scheme, size);
      try {
        const page = await context.newPage();
        await page.goto("/");
        await signInWith(page, KEY());
        await expect(page.getByRole("navigation", { name: /^(Main|Tabs)$/ }).first()).toBeVisible();
        await page.evaluate(() => localStorage.setItem("lph.lang", "en"));
        for (const view of VIEWS.filter((v) => size === DESKTOP || v.phone)) {
          await view.open(page);
          await settle(page);
          await page.screenshot({ path: resolve(OUT, `${view.name}-${scheme}${size.name}.png`) });
        }
      } finally {
        await context.close();
      }
    });
  }
}
