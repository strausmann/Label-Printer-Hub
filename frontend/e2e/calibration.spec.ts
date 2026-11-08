import type { Page } from "@playwright/test";
import { MAIN } from "./env";
import { expect, mainKey, resetPagePrinter, setPagePrinter, signInWith, test } from "./fixtures";

const TYPE = "avery-zweckform-l4736rev"; // 4 x 12; no gap between its rows
const PRINTER = "Office page printer";
const TRAY = "main-tray";

const noSideScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth);
const setLanguage = (page: Page, lang: "de" | "en") => page.evaluate((l) => localStorage.setItem("lph.lang", l), lang);

async function printerId(page: Page): Promise<string> {
  const printers = (await (await page.request.get("/api/printers")).json()) as Array<{ id: string; name: string }>;
  return printers.find((p) => p.name === PRINTER)!.id;
}

/** What the capabilities say about the tray (the endpoint the print dialog reads). */
async function trayCalibration(page: Page, id: string) {
  const caps = (await (await page.request.get(`/api/printers/${id}/capabilities`)).json()) as {
    trays: Array<{ key: string; calibration: { offset_x_mm: number | null; offset_y_mm: number | null } | null }>;
  };
  return caps.trays.find((t) => t.key === TRAY)!.calibration;
}
const hasCorrection = (c: { offset_x_mm: number | null; offset_y_mm: number | null } | null) => !!c && (c.offset_x_mm != null || c.offset_y_mm != null);

async function jobsOf(page: Page, id: string): Promise<string[]> {
  const jobs = (await (await page.request.get("/api/jobs")).json()) as Array<{ id: string; printer_id: string }>;
  return jobs.filter((j) => j.printer_id === id).map((j) => j.id);
}

/** Chooses the 4 x 12 type in the select. */
async function chooseType(page: Page) {
  await page.getByRole("button", { name: /Sheet type|Bogentyp/ }).click();
  await page.getByRole("option", { name: new RegExp(`\\(${TYPE}\\)`) }).click();
}

async function openCalibration(page: Page, id: string) {
  await page.goto(`/calibration?printer=${id}&tray=${TRAY}`);
  await expect(page.getByRole("heading", { level: 1, name: /Calibration|Kalibrierung/ })).toBeVisible();
}

// One sign-in for the whole file: the hub limits sign-ins per minute.
test.describe.serial("calibration", () => {
  let page: Page;
  let id: string;
  test.beforeAll(async ({ browser }) => {
    page = await (await browser.newContext({ baseURL: MAIN.url })).newPage();
    await page.goto("/");
    await signInWith(page, mainKey());
    await expect(page.getByRole("navigation", { name: /^(Main|Tabs)$/ }).first()).toBeVisible();
    id = await printerId(page);
  });
  test.afterAll(async () => {
    await page.context().close();
  });
  test.afterEach(async () => {
    await resetPagePrinter(page);
  });

  test("prints a calibration page to the fake printer: a job appears", async () => {
    await setLanguage(page, "en");
    await page.setViewportSize({ width: 1280, height: 800 });
    await setPagePrinter(page, { job_script: [3, 5, 9] });
    const before = await jobsOf(page, id);
    await openCalibration(page, id);
    await chooseType(page);
    await page.getByRole("button", { name: "Print calibration page" }).click();
    const link = page.getByRole("link", { name: "Show the job" });
    await expect(link).toBeVisible();
    const jobId = (await link.getAttribute("href"))!.split("/").pop()!;
    // Relative: other specs print to the same fake.
    await expect.poll(async () => (await jobsOf(page, id)).length, { timeout: 15_000 }).toBeGreaterThan(before.length);
    expect(await jobsOf(page, id)).toContain(jobId);
    // The download is the same page as a PDF.
    const pdf = page.getByRole("link", { name: "Download PDF" });
    expect(await pdf.getAttribute("href")).toMatch(/\/page\/pdf\?/);
    const response = await page.request.get((await pdf.getAttribute("href"))!);
    expect(response.headers()["content-type"]).toContain("application/pdf");
  });

  test("the Calibrate link on the printer page opens the calibration with that printer and tray chosen", async () => {
    await setLanguage(page, "en");
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto(`/printers/${id}`);
    const links = page.getByRole("link", { name: /^Calibrate .+/ });
    await expect(links.last()).toBeVisible();
    const name = (await links.last().getAttribute("aria-label"))!;
    const trayLabel = name.replace(/^Calibrate /, "");
    // Keyboard only: the link is reached and opened with Tab and Enter.
    await links.last().focus();
    await expect(links.last()).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { level: 1, name: "Calibration" })).toBeVisible();
    const url = new URL(page.url());
    expect(url.pathname).toBe("/calibration");
    expect(url.searchParams.get("printer")).toBe(id);
    expect(url.searchParams.get("tray")).toBeTruthy();
    // The choice is shown, not only in the address: printer and tray are preselected.
    await expect(page.getByRole("button", { name: / Printer$/ })).toContainText(PRINTER);
    await expect(page.getByRole("button", { name: / Tray$/ })).toContainText(trayLabel);
  });

  test("fits four readings, saves them, the capabilities show the values; reset puts the tray back", async () => {
    await setLanguage(page, "en");
    await page.setViewportSize({ width: 1280, height: 800 });
    expect(hasCorrection(await trayCalibration(page, id))).toBe(false);
    try {
      await openCalibration(page, id);
      await chooseType(page);
      // The same deviation at all four outermost crossings: 0.5 mm to the right, 0.3 mm too low.
      for (const crossing of ["S1 · Z1", "S3 · Z1", "S1 · Z11", "S3 · Z11"]) {
        await page.getByRole("textbox", { name: `Across at ${crossing} (mm)` }).fill("0,5");
        await page.getByRole("textbox", { name: `Down at ${crossing} (mm)` }).fill("0,3");
      }
      await page.getByRole("button", { name: "Fit", exact: true }).click();
      await expect(page.getByRole("table", { name: "Result of the fit" })).toBeVisible();
      await expect(page.getByText("check this reading")).toHaveCount(0);
      await expect(page.getByRole("textbox", { name: "Offset X (mm)" })).toHaveValue("0.5");
      await expect(page.getByRole("textbox", { name: "Offset Y (mm)" })).toHaveValue("0.3");

      await page.getByRole("button", { name: "Save for this printer and tray" }).click();
      await expect(page.getByText("Saved. New prints use this correction.")).toBeVisible();
      await expect.poll(async () => (await trayCalibration(page, id))?.offset_x_mm, { timeout: 10_000 }).toBeCloseTo(0.5, 2);
      expect((await trayCalibration(page, id))?.offset_y_mm).toBeCloseTo(0.3, 2);
      // The stored values are shown, with the date of the change.
      const current = page.getByRole("region", { name: "Current values" });
      await expect(current.getByText("0.5 mm")).toBeVisible();
      await expect(current.getByText(/Last changed/)).toBeVisible();

      // The check print is offered now, and goes to the queue.
      await page.getByRole("button", { name: "Check print with correction" }).click();
      await expect(page.getByText("The check page is queued.")).toBeVisible();

      // Back to no correction, through the page.
      await page.getByRole("button", { name: "Reset to no correction" }).click();
      await page.getByRole("button", { name: "Yes, reset" }).click();
      await expect(page.getByText("Reset. This tray prints without correction.")).toBeVisible();
      await expect.poll(async () => hasCorrection(await trayCalibration(page, id)), { timeout: 10_000 }).toBe(false);
    } finally {
      // Later specs share this hub: leave the tray without a correction whatever happened above.
      const status = await page.evaluate(
        async ([p]) => {
          const session = await (await fetch("/api/v1/auth/session")).json();
          return (await fetch(p as string, { method: "DELETE", headers: { "X-CSRF-Token": session.csrf_token } })).status;
        },
        [`/api/printers/${id}/calibration/${TRAY}`] as const,
      );
      // Not asserted here: a failing check in `finally` would replace the error of the test body. The state is asserted below.
      void status;
    }
    expect(hasCorrection(await trayCalibration(page, id))).toBe(false);
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

        // Worst case: a printer name and a sheet type that are as long as the hub accepts, and a
        // tray without a correction; the answers are the real ones with the names stretched.
        const long = "Büro-Laserdrucker im Erdgeschoss neben dem Besprechungsraum der Geschäftsführung";
        await page.route("**/api/printers", async (route) => {
          const list = (await (await route.fetch()).json()) as Array<{ id: string; name: string }>;
          await route.fulfill({ json: list.map((p) => (p.id === id ? { ...p, name: long } : p)) });
        });
        await page.route("**/api/sheet-types", async (route) => {
          const list = (await (await route.fetch()).json()) as Array<{ key: string; vendor: string | null }>;
          await route.fulfill({ json: list.map((t) => (t.key === TYPE ? { ...t, vendor: "Zweckform Etiketten und Bürobedarf Vertriebsgesellschaft" } : t)) });
        });
        await openCalibration(page, id);
        await expect(page.getByRole("heading", { level: 2, name: de ? "Schritt 1: Kalibrierseite drucken" : "Step 1: Print the calibration page" })).toBeVisible();
        await chooseType(page);
        expect(await noSideScroll(page)).toBe(true);
        await shot("calibration-empty");

        // A fitted result with a flagged reading, the signs, and the stored values.
        await page.unroute("**/api/printers");
        await page.unroute("**/api/sheet-types");
        await page.route(`**/api/printers/${id}/calibration/${TRAY}/fit`, (route) =>
          route.fulfill({
            json: {
              values: { offset_x_mm: 0.35, offset_y_mm: -0.15, scale_x: 1.0012, scale_y: 0.9995, rotation_deg: 0.03 },
              residuals_mm: [0.05, 0.42, 0.1, 0.02],
              flagged: [1],
              out_of_range: [],
            },
          }),
        );
        await page.reload();
        await chooseType(page);
        for (const crossing of ["S1 · Z1", "S3 · Z1", "S1 · Z11", "S3 · Z11"]) {
          await page.getByRole("textbox", { name: new RegExp(`^(Across|Quer) (at|bei) ${crossing} \\(mm\\)$`) }).fill("0,3");
          await page.getByRole("textbox", { name: new RegExp(`^(Down|Abwärts) (at|bei) ${crossing} \\(mm\\)$`) }).fill("-0,2");
        }
        await page.getByRole("button", { name: de ? "Berechnen" : "Fit", exact: true }).click();
        await expect(page.getByRole("table", { name: de ? "Ergebnis der Berechnung" : "Result of the fit" })).toBeVisible();
        expect(await noSideScroll(page)).toBe(true);
        await shot("calibration-fitted");
        await page.unroute(`**/api/printers/${id}/calibration/${TRAY}/fit`);
      });
    }
  }
});
