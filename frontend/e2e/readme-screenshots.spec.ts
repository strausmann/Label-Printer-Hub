// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

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
 *   phone-menu      (phone only, no website shot) the menu open as admin
 *   phone-search    (phone only, no website shot) the search dialog with a sheet code typed
 *   sheet-archive   sheet-archive
 *   calibration     calibration
 *   calibration-guide  (phone only) the reading guide of step 2, opened
 *   print-dialog    print-dialog
 *   cart-sheet      cart-sheet
 *   cart-check      cart-check
 *   grocy-labels    grocy-labels
 *   notifications   notifications
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
    menu: "Menu",
    search: "Search",
    overview: "Overview",
    skip: "Skip",
    calibration: "Calibration",
    calibrationPage: /^Calibration page of /,
    guide: "How to read the calibration page",
    crossingFigure: "How to read one crossing",
    item: "Snipe-IT item" as string | undefined,
    preview: "Label preview",
    ontoSheet: "Print onto a sheet",
    ontoSheetButton: "Print onto sheet",
    grocyLabels: "Grocy labels",
    wontPrint: /will not print\./,
    bell: /^Notifications/,
    panel: "Notifications",
    failedEntry: /Failed cable label failed/,
    isNew: "New",
  },
  de: {
    connected: /^Verbunden/,
    menu: "Menü",
    search: "Suchen",
    overview: "Übersicht",
    skip: "Überspringen",
    calibration: "Kalibrierung",
    calibrationPage: /^Kalibrierseite für /,
    guide: "So liest du die Kalibrierseite ab",
    crossingFigure: "So liest du eine Kreuzung ab",
    item: undefined, // the heading names the item in German word order; the preview below proves the page
    preview: "Etikettenvorschau",
    ontoSheet: "Auf einen Bogen drucken",
    ontoSheetButton: "Auf den Bogen drucken",
    grocyLabels: "Grocy-Etiketten",
    wontPrint: /nicht gedruckt\./,
    bell: /^Benachrichtigungen/,
    panel: "Benachrichtigungen",
    failedEntry: /Failed cable label ist fehlgeschlagen/,
    isNew: "Neu",
  },
} satisfies Record<Lang, unknown>;
type Text = (typeof TEXT)["en"];

/** The website name of each view (`hero` for the overview). */
const SITE_SHOT: Record<string, string> = { overview: "hero" };

type View = { name: string; phone: boolean; /** Shown on the phone only (not on the desktop). */ only?: "phone"; open: (page: Page, text: Text) => Promise<void> };

const id = async (page: Page, printer: string) => {
  const printers = (await (await page.request.get("/api/v1/printers")).json()) as Array<{ id: string; name: string }>;
  return printers.find((p) => p.name === printer)!.id;
};

/** Waits until the shell shows the live connection and the web fonts are in, so nothing changes under the camera. */
async function settle(page: Page, text: Text) {
  await expect(page.getByText(text.connected).first()).toBeAttached(); // the sidebar line is hidden on the phone layout; the open phone menu shows one too
  await page.evaluate(() => document.fonts.ready);
  // The bell counts entries that arrive from three queries (jobs, printers with their statuses, sheets): its name stops
  // changing once they have all landed. Three equal readings in a row, so a view is never photographed half-counted.
  const bell = page.locator("header").getByRole("button", { name: text.bell, includeHidden: true });
  let previous: string[] = [];
  await expect
    .poll(
      async () => {
        previous = [...previous, (await bell.getAttribute("aria-label")) ?? ""].slice(-3);
        return previous.length === 3 && previous.every((name) => name === previous[0]);
      },
      { timeout: 20_000, intervals: [400] },
    )
    .toBe(true);
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

/**
 * A cart on a Brother QL with 62 mm tape: two layouts to preview and one item whose link the QR code cannot hold. The
 * hub's QL is not polled, so the tape is served from here (the fixtures have no tape reading for it).
 */
async function fillQlCart(page: Page) {
  const printer = await id(page, "Office QL-820NWB");
  await page.route(new RegExp(`/api/v1/printers/${printer}/status$`), async (route) => {
    const response = await route.fetch();
    const body = (await response.json()) as Record<string, unknown>;
    Object.assign(body, { online: true, polled: true, stale: false, tape_loaded: "62mm", tape_width_mm: 62, last_probe_age_s: 3, note: null });
    await route.fulfill({ response, json: body });
  });
  await page.evaluate((p) => {
    localStorage.setItem("lph.printer", p);
    const line = (app: string, n: string, name: string, content_type: string, copies: number) => ({ app, id: n, name, content_type, copies });
    localStorage.setItem(
      "lph.cart",
      JSON.stringify([line("snipeit", "42", "Cordless drill", "qr_two_lines", 1), line("spoolman", "7", "PLA red", "qr_only", 2), line("snipeit", "a".repeat(250), "Shelf label", "qr_two_lines", 1)]),
    );
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
    // The phone menu open as admin: every area of the sidebar, then the settings sections.
    name: "phone-menu",
    phone: true,
    only: "phone",
    open: async (page, text) => {
      await page.goto("/sheets");
      await expect(page.getByRole("link", { name: "L4736-0001" })).toBeVisible();
      await page.getByRole("button", { name: text.menu, exact: true }).click();
      await expect(page.getByRole("dialog", { name: text.menu })).toBeVisible();
    },
  },
  {
    // The search dialog the magnifier opens on a phone, with a sheet type typed: the field and its results.
    name: "phone-search",
    phone: true,
    only: "phone",
    open: async (page, text) => {
      await page.goto("/sheets");
      await expect(page.getByRole("link", { name: "L4736-0001" })).toBeVisible();
      await page.locator("header").getByRole("button", { name: text.search, exact: true }).click();
      const dialog = page.getByRole("dialog", { name: text.search });
      await expect(dialog).toBeVisible();
      await dialog.getByRole("combobox", { name: text.search }).fill("L4736");
      await expect(dialog.getByRole("option").first()).toBeVisible();
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
    // Step 2 with the guide open on the phone: the drawing of one crossing and its legend. The guide is
    // collapsed in the `calibration` view above.
    name: "calibration-guide",
    phone: true,
    only: "phone",
    open: async (page, text) => {
      await page.goto(`/calibration?printer=${await id(page, "Office page printer")}&tray=main-tray`);
      await expect(page.getByRole("heading", { level: 1, name: text.calibration })).toBeVisible();
      const trigger = page.getByRole("button", { name: text.guide });
      await trigger.click();
      await expect(trigger).toHaveAttribute("aria-expanded", "true");
      await expect(page.getByRole("img", { name: text.crossingFigure })).toBeVisible();
      // Bring the guide's top below the sticky top bar: the drawing and the start of its legend fill the view.
      await trigger.evaluate((el) => window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - 72));
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
  {
    name: "cart-check",
    phone: false,
    open: async (page, text) => {
      await page.goto("/");
      await fillQlCart(page);
      await page.goto("/cart");
      await expect(page.getByText(text.wontPrint)).toBeVisible({ timeout: 30_000 });
      await expect(page.getByRole("img", { name: text.preview })).toHaveCount(2);
      // Bring the flagged item's top below the sticky top bar: its note, the layout choice and the previews fit one view.
      await page.getByRole("link", { name: "Shelf label" }).evaluate((el) => window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - 88));
    },
  },
  {
    name: "grocy-labels",
    phone: false,
    open: async (page, text) => {
      await page.goto("/settings/integrations");
      const panel = page.getByRole("group", { name: text.grocyLabels });
      await expect(panel).toBeVisible();
      // Bring the panel's top below the sticky top bar.
      await panel.evaluate((el) => window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - 88));
    },
  },
  {
    // The panel open on the seeded jobs and printers: the failed job leads, nothing read yet.
    name: "notifications",
    phone: true,
    open: async (page, text) => {
      // The entries come from the printers' statuses, and a cold hub reads them in its own time ("not monitored" until the
      // first probe has landed). The two printers that are probed are served as ready from here, like `fillQlCart` does,
      // so the list is the same in every run; the bench printer is never polled and stays "Not monitored" on its own.
      for (const name of ["Office QL-820NWB", "Office page printer"]) {
        const printer = await id(page, name);
        await page.route(new RegExp(`/api/v1/printers/${printer}/status$`), async (route) => {
          const response = await route.fetch();
          const body = (await response.json()) as Record<string, unknown>;
          Object.assign(body, { online: true, polled: true, stale: false, last_probe_age_s: 3, note: null, error_state: null, last_error: null });
          await route.fulfill({ response, json: body });
        });
      }
      await page.goto("/");
      await page.getByRole("button", { name: text.bell }).click();
      const panel = page.getByRole("dialog", { name: text.panel });
      await expect(panel.getByRole("link", { name: text.failedEntry })).toBeVisible();
      await expect(panel.getByText(text.isNew).first()).toBeVisible();
    },
  },
];

async function newContext(browser: Browser, scheme: Scheme, size: Size, lang: Lang): Promise<BrowserContext> {
  const context = await browser.newContext({
    baseURL: SHOTS.url,
    viewport: { width: size.width, height: size.height },
    deviceScaleFactor: 1,
    colorScheme: scheme,
    serviceWorkers: "block",
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
    for (const view of VIEWS.filter((v) => (size === DESKTOP ? v.only !== "phone" : v.phone))) {
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
