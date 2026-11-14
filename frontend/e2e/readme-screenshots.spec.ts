import { copyFileSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test";
import { SHOTS } from "./env";
import { signInWith } from "./fixtures";

/**
 * Renders the screenshots of the README into `docs/screenshots/` and those of the website (run by `pnpm screenshots`,
 * never by `pnpm e2e`).
 *
 * The views, in the order the README shows them, and the website shot each one maps to. The website gets every
 * desktop view in English and German, light and dark, as PNG in `SITE_PNG`; `scripts/optimise-screenshots.mjs` turns
 * them into `website/src/assets/screens/<shot>.<en|de>.<light|dark>.webp`:
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
 * and `sheets`. File names are `<view>-<light|dark>[-phone].png`. The README shows English only; the German website
 * shots are the same views with the UI language set to German.
 *
 * Why two runs give the same bytes: the hub is the e2e app on its fixtures, and every seeded job and sheet carries
 * `FIXTURE_TIME` (`E2E_FIXTURE_TIME`, see `backend/tests/e2e_app.py`); the browser clock is fixed (`CLOCK`), its
 * locale and time zone are pinned, motion is off, the fonts are the bundled ones and the device scale factor is 1.
 */
const OUT = resolve(import.meta.dirname, "..", "..", "docs", "screenshots");
/** Lossless intermediates of the website shots; `scripts/optimise-screenshots.mjs` reads them. */
export const SITE_PNG = resolve(import.meta.dirname, ".tmp", "site-shots");
const CLOCK = new Date("2026-11-01T09:00:00Z");
const KEY = () => readFileSync(SHOTS.keyFile, "utf8").trim();

type Scheme = "light" | "dark";
type Size = { name: "" | "-phone"; width: number; height: number };
const DESKTOP: Size = { name: "", width: 1440, height: 900 };
const PHONE: Size = { name: "-phone", width: 390, height: 844 };

type Lang = "en" | "de";

/** The UI texts the views wait for, from the message catalogues of each language. */
const TEXT = {
  en: {
    connected: /^Connected/,
    overview: "Overview",
    skip: "Skip",
    calibration: "Calibration",
    calibrationPage: /^Calibration page of /,
    item: "Snipe-IT item" as string | undefined,
    preview: "Label preview",
    ontoSheet: "Print onto a sheet",
    ontoSheetButton: "Print onto sheet",
  },
  de: {
    connected: /^Verbunden/,
    overview: "Übersicht",
    skip: "Überspringen",
    calibration: "Kalibrierung",
    calibrationPage: /^Kalibrierseite für /,
    item: undefined, // the heading names the item in German word order; the preview below proves the page
    preview: "Etikettenvorschau",
    ontoSheet: "Auf einen Bogen drucken",
    ontoSheetButton: "Auf den Bogen drucken",
  },
} satisfies Record<Lang, unknown>;
type Text = (typeof TEXT)["en"];

/** The website name of each view (`hero` for the overview). */
const SITE_SHOT: Record<string, string> = { overview: "hero" };

type View = { name: string; phone: boolean; open: (page: Page, text: Text) => Promise<void> };

const id = async (page: Page, printer: string) => {
  const printers = (await (await page.request.get("/api/v1/printers")).json()) as Array<{ id: string; name: string }>;
  return printers.find((p) => p.name === printer)!.id;
};

/** Waits until the shell shows the live connection and the web fonts are in, so nothing changes under the camera. */
async function settle(page: Page, text: Text) {
  await expect(page.getByText(text.connected)).toBeAttached(); // hidden on the phone layout
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
    open: async (page, text) => {
      await page.goto("/");
      await expect(page.getByRole("heading", { level: 1, name: text.overview })).toBeVisible();
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
    open: async (page, text) => {
      await page.goto(`/printers/${await id(page, "Bench PT-P750W")}`);
      await expect(page.getByRole("heading", { level: 1, name: "Bench PT-P750W" })).toBeVisible();
      await expect(page.getByText("12 mm").first()).toBeVisible();
      // The roll prompt first says "Loading...", then offers the colours: wait for the second state.
      await expect(page.getByRole("button", { name: text.skip })).toBeVisible();
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
    open: async (page, text) => {
      await page.goto(`/calibration?printer=${await id(page, "Office page printer")}&tray=main-tray`);
      await expect(page.getByRole("heading", { level: 1, name: text.calibration })).toBeVisible();
      await expect(page.getByRole("img", { name: text.calibrationPage })).toBeVisible();
    },
  },
  {
    name: "print-dialog",
    phone: false,
    open: async (page, text) => {
      await page.goto("/asset/42");
      await expect(page.getByRole("heading", { level: 1, name: text.item })).toBeVisible();
      const preview = page.getByRole("img", { name: text.preview });
      await expect(preview).toBeVisible();
      await expect.poll(() => preview.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0)).toBe(true);
    },
  },
  {
    name: "cart-sheet",
    phone: false,
    open: async (page, text) => {
      await page.goto("/");
      await fillCart(page);
      await page.goto("/cart?sheet=L4736-0001");
      await expect(page.getByRole("heading", { level: 2, name: text.ontoSheet })).toBeVisible();
      await expect(page.getByRole("button", { name: text.ontoSheetButton })).toBeEnabled({ timeout: 30_000 });
    },
  },
];

async function newContext(browser: Browser, scheme: Scheme, size: Size, lang: Lang): Promise<BrowserContext> {
  const context = await browser.newContext({
    baseURL: SHOTS.url,
    viewport: { width: size.width, height: size.height },
    deviceScaleFactor: 1,
    colorScheme: scheme,
    reducedMotion: "reduce",
    locale: lang === "de" ? "de-DE" : "en-US",
    timezoneId: "UTC",
  });
  await context.clock.install({ time: CLOCK });
  return context;
}

/** Signs in, sets the UI language and photographs the views of `size` in one browser context. */
async function shoot(browser: Browser, scheme: Scheme, size: Size, lang: Lang, save: (view: View, png: Buffer) => void) {
  const context = await newContext(browser, scheme, size, lang);
  try {
    const page = await context.newPage();
    await page.goto("/");
    await signInWith(page, KEY());
    await expect(page.getByRole("navigation").first()).toBeVisible();
    await page.evaluate((l) => localStorage.setItem("lph.lang", l), lang);
    for (const view of VIEWS.filter((v) => size === DESKTOP || v.phone)) {
      await view.open(page, TEXT[lang]);
      await settle(page, TEXT[lang]);
      save(view, await page.screenshot());
    }
  } finally {
    await context.close();
  }
}

const sitePng = (view: View, lang: Lang, scheme: Scheme) =>
  resolve(SITE_PNG, `${SITE_SHOT[view.name] ?? view.name}.${lang}.${scheme}.png`);

for (const scheme of ["light", "dark"] as const) {
  for (const size of [DESKTOP, PHONE]) {
    test(`README screenshots, ${scheme}${size.name}`, async ({ browser }) => {
      test.setTimeout(180_000);
      mkdirSync(SITE_PNG, { recursive: true });
      await shoot(browser, scheme, size, "en", (view, png) => {
        const readme = resolve(OUT, `${view.name}-${scheme}${size.name}.png`);
        writeFileSync(readme, png);
        // The English desktop shot is also the website's English shot.
        if (size === DESKTOP) copyFileSync(readme, sitePng(view, "en", scheme));
      });
    });
  }
  test(`website screenshots in German, ${scheme}`, async ({ browser }) => {
    test.setTimeout(180_000);
    mkdirSync(SITE_PNG, { recursive: true });
    await shoot(browser, scheme, DESKTOP, "de", (view, png) => writeFileSync(sitePng(view, "de", scheme), png));
  });
}
