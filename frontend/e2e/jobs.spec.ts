import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import type { Page } from "@playwright/test";
import { expect, resetPagePrinter, setPagePrinter, test } from "./fixtures";

const SHOTS = process.env.E2E_SHOTS_DIR;
const shot = async (page: Page, name: string) => {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: resolve(SHOTS, name), fullPage: true });
};
const noSideScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);

test.describe("jobs", () => {
  test("retry a failed job", async ({ signedInPage: page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Jobs" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Jobs" })).toBeVisible();
    await shot(page, "task-12-jobs-desktop.png");

    await page.getByRole("radio", { name: "Failed" }).click();
    await page.getByRole("link", { name: "Failed cable label" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Failed cable label" })).toBeVisible();
    await expect(page.getByRole("alert").filter({ hasText: "Printer reported: cover open" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Cancel" })).toHaveCount(0);
    await shot(page, "task-12-job-desktop.png");

    const failedUrl = page.url();
    await page.getByRole("button", { name: "Retry" }).click();
    // The retry is a new job: another address, and it is not the failed one.
    await expect(page).not.toHaveURL(failedUrl);
    await expect(page).toHaveURL(/\/jobs\/[0-9a-f-]{36}$/);
    // The retried job is queued for real now, so its state (and thus a Retry button) depends on
    // what the mock printer does with it; only its identity is asserted here.
    await expect(page.getByRole("heading", { level: 1, name: "Failed cable label" })).toBeVisible();

    await page.setViewportSize({ width: 390, height: 844 });
    await shot(page, "task-12-job-phone.png");
    expect(await noSideScroll(page)).toBe(true);
    await page.getByRole("navigation", { name: "Tabs" }).getByRole("link", { name: "Jobs" }).click();
    await shot(page, "task-12-jobs-phone.png");
    expect(await noSideScroll(page)).toBe(true);
  });
});

const TYPE_KEY = "avery-zweckform-l4736rev";

/** The name the UI gives the sheet type: "<vendor> <first product code>". */
async function typeName(page: Page): Promise<string> {
  const type = (await (await page.request.get(`/api/v1/sheet-types/${TYPE_KEY}`)).json()) as { vendor: string | null; product_codes: string[] };
  return type.vendor && type.product_codes[0] ? `${type.vendor} ${type.product_codes[0]}` : (type.product_codes[0] ?? TYPE_KEY);
}

/** A calibration page job on the fake page printer: it needs no sheet and no cells. */
async function startPageJob(page: Page): Promise<string> {
  const printers = (await (await page.request.get("/api/v1/printers")).json()) as Array<{ id: string; name: string }>;
  const printer = printers.find((p) => p.name === "Office page printer")!;
  const csrf = await page.evaluate(async () => ((await (await fetch("/api/v1/auth/session")).json()) as { csrf_token: string }).csrf_token);
  const response = await page.request.post(`/api/v1/printers/${printer.id}/calibration/main-tray/page`, {
    data: { type: TYPE_KEY },
    headers: { "X-CSRF-Token": csrf },
  });
  expect(response.ok(), await response.text()).toBe(true);
  return ((await response.json()) as { job_id: string }).job_id;
}

test.describe("page jobs", () => {
  test.afterEach(async ({ signedInPage: page }) => {
    await resetPagePrinter(page);
  });

  test("a page job shows where it stands at the printer, in order, until it is done", async ({ signedInPage: page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.evaluate(() => localStorage.setItem("lph.lang", "en"));
    // pending, pending, processing, completed: one step per hub poll.
    await setPagePrinter(page, { job_script: [3, 3, 5, 9] });
    const jobId = await startPageJob(page);
    await page.goto(`/jobs/${jobId}`);
    // The title names the sheet type by its label, not by the key the payload stores.
    const label = await typeName(page);
    expect(label).not.toBe(TYPE_KEY);
    await expect(page.getByRole("heading", { level: 1, name: `Calibration page · ${label} v1` })).toBeVisible();

    const info = page.getByRole("region", { name: "Calibration page" });
    const seen: string[] = [];
    for (const text of ["Waiting at the printer", "Printing"]) {
      await expect(info.getByRole("status").getByText(text, { exact: true })).toBeVisible({ timeout: 30_000 });
      seen.push(text);
    }
    expect(seen).toEqual(["Waiting at the printer", "Printing"]);
    await expect(page.getByText("Done", { exact: true }).first()).toBeVisible({ timeout: 30_000 });
    await expect(info.getByRole("status").getByText("Printing", { exact: true })).toHaveCount(0);
    await page.screenshot({ path: `${SHOTS ?? "test-results"}/page-job-done.png`, fullPage: true });
  });

  test("a page job stopped at the printer says so", async ({ signedInPage: page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.evaluate(() => localStorage.setItem("lph.lang", "en"));
    await setPagePrinter(page, { job_script: [3, 6, 6, 6, 6, 6, 6, 6, 6, 6, 9] });
    const jobId = await startPageJob(page);
    await page.goto(`/jobs/${jobId}`);
    const info = page.getByRole("region", { name: "Calibration page" });
    await expect(info.getByRole("status").getByText("Stopped at the printer", { exact: true })).toBeVisible({ timeout: 30_000 });
    await shot(page, "task-10-stopped-1280-en-light.png");
    // The printer's own reason: the job says only "printer-stopped", the printer status names the cause.
    await setPagePrinter(page, { printer_state: 5, reasons: ["toner-empty-error"] });
    await expect(info.getByRole("status").getByText("Stopped at the printer · toner empty", { exact: true })).toBeVisible({ timeout: 15_000 });
    // The job list says the same.
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Jobs" }).click();
    await expect(page.getByRole("list", { name: "Jobs" }).getByText("Stopped at the printer · toner empty").first()).toBeVisible();
    await page.goBack();
    // A reload keeps the sub-state: the reconnect snapshot carries it.
    await page.reload();
    await expect(info.getByRole("status")).toContainText("Stopped at the printer", { timeout: 15_000 });
    await shot(page, "task-10-stopped-reason-1280-en-light.png");
    await expect(page.getByText("Done", { exact: true }).first()).toBeVisible({ timeout: 30_000 });
  });
});

// A sheet page that was interrupted on the 189-cell sheet: 120 cells, 90 of them unconfirmed. The
// answers are fabricated in the browser so that the real build lays out the worst case.
const WORST_ID = "dddddddd-0000-4000-8000-0000000000aa";
const WORST_CODE = "L4731-0001";
const range = (n: number, from = 1) => Array.from({ length: n }, (_, i) => i + from);

test.describe("page job worst case", () => {
  for (const [lang, size] of [
    ["de", { width: 360, height: 780 }],
    ["en", { width: 1280, height: 800 }],
  ] as const) {
    for (const scheme of ["light", "dark"] as const) {
      test(`an interrupted page job with 120 cells, ${lang} at ${size.width} px, ${scheme}`, async ({ signedInPage: page }) => {
        const printers = (await (await page.request.get("/api/v1/printers")).json()) as Array<{ id: string; name: string }>;
        const printerId = printers.find((p) => p.name === "Office page printer")!.id;
        const now = new Date().toISOString();
        await page.route(`**/api/v1/jobs/${WORST_ID}`, (route) =>
          route.fulfill({
            json: {
              id: WORST_ID,
              printer_id: printerId,
              template_key: null,
              state: "failed",
              error: "Der Drucker hat den Auftrag abgebrochen, nachdem er begonnen hatte (interrupted).",
              result: null,
              created_at: now,
              updated_at: now,
              started_at: now,
              finished_at: now,
              payload: {
                kind: "sheet_page",
                detail: {
                  sheet_code: WORST_CODE,
                  cells: range(120).map((cell) => ({ cell })),
                  id_cell: { cell: 189 },
                  job_summary: { sheet_code: WORST_CODE, cell_count: 120 },
                },
              },
            },
          }),
        );
        await page.route(`**/api/v1/sheets/${WORST_CODE}`, (route) =>
          route.fulfill({
            json: {
              code: WORST_CODE,
              state: "active",
              cells: range(90, 31).map((cell) => ({ cell, state: "unconfirmed", source: "grocy", ref: null, purpose: null, marked_by_hand: false, job_id: WORST_ID, updated_at: now })),
            },
          }),
        );
        await page.evaluate((l) => localStorage.setItem("lph.lang", l), lang);
        await page.emulateMedia({ colorScheme: scheme });
        await page.setViewportSize(size);
        await page.goto(`/jobs/${WORST_ID}`);
        const de = lang === "de";
        await expect(page.getByRole("heading", { level: 1, name: de ? `Bogen ${WORST_CODE} · 120 Etiketten` : `Sheet ${WORST_CODE} · 120 labels` })).toBeVisible();
        await expect(page.getByText(de ? "Nicht bestätigt" : "Not confirmed")).toBeVisible();
        await expect(page.getByRole("link", { name: de ? "Zellen auf dem Bogen klären" : "Settle the cells on the sheet" })).toBeVisible();
        expect(await noSideScroll(page)).toBe(true);
        await shot(page, `task-10-interrupted-${size.width}-${lang}-${scheme}.png`);
      });
    }
  }
});
