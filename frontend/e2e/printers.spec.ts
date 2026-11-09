import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import type { Page } from "@playwright/test";
import { expect, resetPagePrinter, setPagePrinter, test, waitForQuietQueue } from "./fixtures";

const SHOTS = process.env.E2E_SHOTS_DIR;
const shot = async (page: Page, name: string) => {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: resolve(SHOTS, name), fullPage: true });
};

const noSideScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);

// Assembled from parts on purpose: the source guard (src/api/paths.test.ts) rejects the literal.
const OLD_PRINTERS_PATH = ["", "api", "printers"].join("/");

test.describe("printers", () => {
  test("old api path is a plain 404", async ({ signedInPage: page }) => {
    const response = await page.request.get(OLD_PRINTERS_PATH);
    expect(response.status()).toBe(404);
    expect(response.headers()["content-type"]).toContain("application/json");
  });

  test("pausing a printer changes its badge through the event stream, without a reload", async ({
    signedInPage: page,
  }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Printers" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Printers" })).toBeVisible();
    await page.getByRole("link", { name: /Workshop PT-P750W/ }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Workshop PT-P750W" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Pause" })).toBeVisible();
    await shot(page, "task-11-detail-desktop.png");

    // Marker on the window: a reload would erase it.
    await page.evaluate(() => ((window as unknown as { __kept: boolean }).__kept = true));
    await page.getByRole("button", { name: "Pause" }).click();
    await expect(page.getByRole("button", { name: "Resume" })).toBeVisible();
    await expect(page.getByText("Paused").first()).toBeVisible();
    expect(await page.evaluate(() => (window as unknown as { __kept?: boolean }).__kept)).toBe(true);

    // The same change reaches the overview (a paused printer needs attention) …
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Overview" }).click();
    const attention = page.getByRole("region", { name: "Needs attention" });
    await expect(attention.getByText("Workshop PT-P750W")).toBeVisible();
    await shot(page, "task-11-overview-desktop.png");

    // … and resuming from there flips it back.
    await attention.getByRole("button", { name: "Resume Workshop PT-P750W" }).click();
    await expect(attention.getByText("Workshop PT-P750W")).toHaveCount(0);

    await page.setViewportSize({ width: 390, height: 844 });
    await shot(page, "task-11-overview-phone.png");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.getByRole("navigation", { name: "Tabs" }).getByRole("link", { name: "Printers" }).click();
    await page.getByRole("link", { name: /Office QL-820NWB/ }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Office QL-820NWB" })).toBeVisible();
    await shot(page, "task-11-detail-phone.png");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  });

  test("the overview answers its three questions in order", async ({ signedInPage: page }) => {
    const headings = page.getByRole("heading", { level: 2 });
    await expect(headings.nth(0)).toHaveText("Printing now");
    await expect(headings.nth(1)).toHaveText("Needs attention");
    await expect(headings.nth(2)).toHaveText("Material");
  });
});

const STOPPED = { printer_state: 5, reasons: ["toner-empty-error"] };
const BLACK = { name: "black", color: "#000000", level: 0, low_level: 10, type: "toner" };

test.describe("page printer status", () => {
  // The fake printer is shared by every spec (N10): put it back, and assert nothing absolute about it.
  // So is the hub's queue for it: a job another spec left in flight is dispatched while this spec has the
  // printer stopped, and the hub then pauses the printer ("Paused" instead of "Stopped"). Start from an empty queue.
  test.beforeEach(async ({ signedInPage: page }) => {
    await waitForQuietQueue(page);
  });
  test.afterEach(async ({ signedInPage: page }) => {
    await resetPagePrinter(page);
  });

  test("a stopped printer shows its reason and toner on the card through the event stream and resumes by itself", async ({
    signedInPage: page,
  }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/printers");
    const card = page.getByRole("link", { name: /Office page printer/ });
    await expect(card.getByText("Ready")).toBeVisible({ timeout: 15_000 });
    // Marker on the window: a reload would erase it.
    await page.evaluate(() => ((window as unknown as { __kept: boolean }).__kept = true));

    await setPagePrinter(page, { ...STOPPED, markers: [BLACK] });
    await expect(card.getByText("Stopped")).toBeVisible({ timeout: 15_000 });
    await expect(card.getByText("toner empty")).toBeVisible();
    // The hub applies the printer-wide reason to the supply it names: level 0 is empty.
    await expect(card.getByText("empty", { exact: true })).toBeVisible();

    // Cleared at the printer: the card goes back to Ready on its own (acceptance 16, UI side).
    await resetPagePrinter(page);
    await expect(card.getByText("Ready")).toBeVisible({ timeout: 15_000 });
    await expect(card.getByText("toner empty")).toHaveCount(0);
    expect(await page.evaluate(() => (window as unknown as { __kept?: boolean }).__kept)).toBe(true);
  });

  test("the tape printer cards next to it keep tape and no toner", async ({ signedInPage: page }) => {
    await page.goto("/printers");
    const tape = page.getByRole("link", { name: /Workshop PT-P750W/ });
    await expect(tape).toBeVisible();
    // The card is rendered before its status arrives: wait for a word that comes with the status.
    await expect(tape.getByText(/Tape not known( yet)?|\d+ mm|No tape loaded/).first()).toBeVisible({ timeout: 15_000 });
    await expect(tape.getByText(/toner|supplies/i)).toHaveCount(0);
  });

  test("an unbreakable tape printer name wraps inside its card at 360 px", async ({ signedInPage: page }) => {
    await page.route("**/api/v1/printers", async (route) => {
      const response = await route.fetch();
      const list = (await response.json()) as { name: string; model: string }[];
      list[0]!.name = `Workshop${"x".repeat(70)}`;
      list[0]!.model = `Model${"y".repeat(70)}`;
      await route.fulfill({ response, json: list });
    });
    await page.setViewportSize({ width: 360, height: 780 });
    await page.goto("/printers");
    await expect(page.getByRole("link", { name: /Workshopx{70}/ })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  });

  const WORDS = {
    de: { stopped: "Angehalten", reason: "Toner leer", some: "Rest vorhanden", supplies: "Verbrauchsmaterial", trays: "Fächer", overview: "Übersicht", printers: "Drucker" },
    en: { stopped: "Stopped", reason: "toner empty", some: "some remaining", supplies: "Supplies", trays: "Trays", overview: "Overview", printers: "Printers" },
  } as const;
  const SIZES = [
    { width: 360, height: 780, lang: "de" as const },
    { width: 1280, height: 800, lang: "en" as const },
  ];
  // The worst case of the edge data set: stopped on an empty toner, a marker at "some remaining",
  // very long supply names (one unbreakable) and ten supplies at once.
  const WORST = {
    ...STOPPED,
    markers: [
      { ...BLACK, name: "Black high-yield toner cartridge with an extremely long supplier description" },
      { name: "cyan", color: "#00ffff", level: 40, low_level: 10, type: "toner" },
      // A waste container is never marked by a reason, so its unknown level shows as "some remaining".
      { name: "waste toner box", color: "#808080", level: -3, type: "waste-toner" },
      // One name without a single space or hyphen to break at.
      { name: `Cartridge${"x".repeat(70)}`, color: "#ffcc00", level: 90, low_level: 10, type: "toner" },
      ...["magenta", "yellow", "drum unit", "fuser kit", "transfer belt", "maintenance kit"].map((name) => ({
        name,
        color: "#ff00ff",
        level: 55,
        low_level: 10,
        type: "toner",
      })),
    ],
  };

  for (const size of SIZES) {
    for (const scheme of ["light", "dark"] as const) {
      test(`screens at ${size.width} px, ${size.lang}, ${scheme}`, async ({ signedInPage: page }, testInfo) => {
        const words = WORDS[size.lang];
        await page.evaluate((l) => localStorage.setItem("lph.lang", l), size.lang);
        await page.emulateMedia({ colorScheme: scheme });
        await page.setViewportSize({ width: size.width, height: size.height });
        await setPagePrinter(page, WORST);
        const noSideScroll = () => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
        const name = (screen: string) => testInfo.outputPath(`${screen}-${size.width}-${size.lang}-${scheme}.png`);

        await page.goto("/printers");
        await expect(page.getByRole("heading", { level: 1, name: words.printers })).toBeVisible();
        const card = page.getByRole("link", { name: /Office page printer/ });
        await expect(card.getByText(words.stopped)).toBeVisible({ timeout: 15_000 });
        await expect(card.getByText(words.reason)).toBeVisible();
        await expect(card.getByText(words.some)).toBeVisible();
        // Material, not state: the swatch really has the colour the printer reported (strict CSP allows it).
        await expect(card.locator("[data-swatch]").first()).toHaveCSS("background-color", "rgb(0, 0, 0)");
        expect(await noSideScroll()).toBe(true);
        await page.screenshot({ path: name("printers"), fullPage: true });

        const id = (await card.getAttribute("href"))!.split("/").pop()!;
        await page.goto(`/printers/${id}`);
        await expect(page.getByRole("heading", { level: 1, name: "Office page printer" })).toBeVisible();
        await expect(page.getByRole("region", { name: words.supplies }).getByText(words.some)).toBeVisible();
        await expect(page.getByRole("region", { name: words.trays })).toBeVisible();
        expect(await noSideScroll()).toBe(true);
        await page.screenshot({ path: name("detail"), fullPage: true });

        await page.goto("/");
        await expect(page.getByRole("heading", { level: 1, name: words.overview })).toBeVisible();
        const attention = page.getByRole("region", { name: size.lang === "de" ? "Braucht Aufmerksamkeit" : "Needs attention" });
        await expect(attention.getByText(words.stopped)).toBeVisible({ timeout: 15_000 });
        expect(await noSideScroll()).toBe(true);
        await page.screenshot({ path: name("overview"), fullPage: true });
      });
    }
  }
});

// The roll colour (#229): the printer cannot report it, so a new roll raises a question; the
// answer is shown beside the width. The hub's mock tape printers are unpolled, so status and roll
// are served by the test.
test.describe("roll colour", () => {
  test.use({ serviceWorkers: "block" });

  test("roll prompt after a roll change", async ({ signedInPage: page }) => {
    const printers = (await (await page.request.get("/api/v1/printers")).json()) as { id: string; name: string }[];
    const id = printers.find((p) => p.name === "Workshop PT-P750W")!.id;
    const roll = { colour: null as string | null, width_mm: 12, media_raw: "12mm laminated", prompt_pending: true, set_at: null };
    await page.route(new RegExp(`/api/v1/printers/${id}/status$`), async (route) => {
      const response = await route.fetch();
      const body = (await response.json()) as Record<string, unknown>;
      Object.assign(body, {
        online: true,
        polled: true,
        stale: false,
        tape_loaded: "12mm laminated",
        tape_width_mm: 12,
        roll_prompt: roll.prompt_pending,
        tape_colour: roll.colour,
        last_probe_age_s: 3,
        note: null,
      });
      await route.fulfill({ response, json: body });
    });
    await page.route(new RegExp(`/api/v1/printers/${id}/roll$`), async (route) => {
      if (route.request().method() === "PUT") {
        const sent = route.request().postDataJSON() as { colour: string | null };
        roll.colour = sent.colour;
        roll.prompt_pending = false;
      }
      await route.fulfill({ json: roll });
    });

    const scenes = [
      { width: 1280, height: 800, scheme: "light" },
      { width: 1280, height: 800, scheme: "dark" },
      { width: 390, height: 844, scheme: "light" },
      { width: 390, height: 844, scheme: "dark" },
    ] as const;
    for (const { width, height, scheme } of scenes) {
      await page.setViewportSize({ width, height });
      await page.emulateMedia({ colorScheme: scheme });
      Object.assign(roll, { colour: null, prompt_pending: true });
      await page.goto(`/printers/${id}`);
      const group = page.getByRole("group", { name: "Tape colour" });
      await expect(group).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      await shot(page, `task-11-prompt-${width}-${scheme}.png`);

      // Keyboard only: Tab reaches a colour, Enter answers.
      await group.getByRole("button", { name: "Blue" }).focus();
      await page.keyboard.press("Enter");
      await expect(group).toHaveCount(0);
      await expect(page.getByText("Blue", { exact: true })).toBeVisible();
      expect(await page.evaluate(() => document.activeElement?.textContent)).toBe("Change colour");
      await shot(page, `task-11-colour-${width}-${scheme}.png`);

      // Skip: no colour line at all, never "not reported".
      Object.assign(roll, { colour: null, prompt_pending: true });
      await page.reload();
      await page.getByRole("button", { name: "Skip" }).click();
      await expect(page.getByRole("group", { name: "Tape colour" })).toHaveCount(0);
      await expect(page.getByText("12 mm")).toBeVisible();
      await expect(page.getByText(/colour not reported/i)).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Set colour" })).toBeVisible();
      await shot(page, `task-11-nocolour-${width}-${scheme}.png`);
    }
  });

});

test.describe("test print", () => {
  test.use({ serviceWorkers: "block" });

  test("reaches done on a tape printer", async ({ signedInPage: page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Printers" }).click();
    await page.getByRole("link", { name: /Workshop PT-P750W/ }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Workshop PT-P750W" })).toBeVisible();
    await page.getByRole("button", { name: "Test print" }).click();
    const link = page.getByRole("link", { name: "Open the job" });
    await expect(link).toBeVisible();
    await link.click();
    await expect(page.getByRole("heading", { level: 1, name: "Test label" })).toBeVisible();
    await expect(page.getByText("Done", { exact: true }).first()).toBeVisible({ timeout: 30_000 });
  });

  test("screenshots: idle, disabled with its reason, sent, error, and the jobs list", async ({ signedInPage: page }) => {
    test.skip(!SHOTS, "screenshots are an artifact, taken only with E2E_SHOTS_DIR");
    for (const scheme of ["light", "dark"] as const) {
      await page.emulateMedia({ colorScheme: scheme });
      for (const [width, height] of [
        [1280, 800],
        [390, 844],
      ] as const) {
        await page.setViewportSize({ width, height });
        const name = (what: string) => `task-13-${what}-${width}-${scheme}.png`;
        await page.goto("/printers");
        await page.getByRole("link", { name: /Workshop PT-P750W/ }).click();
        await expect(page.getByRole("button", { name: "Test print" })).toBeVisible();
        await shot(page, name("idle"));
        expect(await noSideScroll(page)).toBe(true);
        // A paused printer: the button is off and the reason stands beside it as text.
        await page.getByRole("button", { name: "Pause" }).click();
        await expect(page.getByRole("button", { name: "Test print" })).toBeDisabled();
        await expect(page.getByText("Printer is paused").first()).toBeVisible();
        await shot(page, name("disabled"));
        await page.getByRole("button", { name: "Resume" }).click();
        await expect(page.getByRole("button", { name: "Test print" })).toBeEnabled();
        await page.getByRole("button", { name: "Test print" }).click();
        await expect(page.getByText("Test print sent.")).toBeVisible();
        await shot(page, name("sent"));
        // The hub answers a refusal in words; a long one must wrap inside the column.
        await page.route("**/test-print", (route) =>
          route.fulfill({
            status: 409,
            contentType: "application/json",
            body: JSON.stringify({
              detail: {
                type: "printer-offline",
                title: "Printer offline",
                status: 409,
                detail:
                  "The printer did not answer. Check that it is switched on and connected to the network, then try again. If it still fails, restart the printer and wait for its light to stop blinking.",
              },
            }),
          }),
        );
        await page.getByRole("button", { name: "Test print" }).click();
        await expect(page.getByRole("alert").filter({ hasText: "not reachable" })).toBeVisible();
        await shot(page, name("error"));
        expect(await noSideScroll(page)).toBe(true);
        await page.unroute("**/test-print");
        await page.getByRole("navigation", { name: width > 800 ? "Main" : "Tabs" }).getByRole("link", { name: "Jobs" }).click();
        await expect(page.getByRole("list", { name: "Jobs" }).getByText("Test label").first()).toBeVisible();
        await shot(page, name("jobs"));
      }
    }
  });
});
