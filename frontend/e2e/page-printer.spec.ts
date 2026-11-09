import { expect, pagePrinterControl, resetPagePrinter, setPagePrinter, test } from "./fixtures";

const SHOTS = process.env.E2E_SHOTS_DIR;

// The seed data the later sheet specs rely on (creation order is fixed, see `backend/tests/e2e_app.py`).
const SEEDED_CODES = {
  partlyUsed: "L4736-0001",
  full: "L4736-0002",
  discarded: "L4736-0003",
  edge: "L4731-0001",
};

test.describe("page printer test hub", () => {
  test.afterEach(async ({ page }) => {
    await resetPagePrinter(page);
  });

  test("lists the page printer next to the two tape printers", async ({ signedInPage: page }) => {
    await page.goto("/printers");
    await expect(page.getByRole("link", { name: /Office page printer/ })).toBeVisible();
    await expect(page.getByRole("link", { name: /Workshop PT-P750W/ })).toBeVisible();
    await expect(page.getByRole("link", { name: /Office QL-820NWB/ })).toBeVisible();
  });

  test("the control path answers JSON, never the app shell", async ({ signedInPage: page }) => {
    const control = await pagePrinterControl(page);
    expect(control.uri).toMatch(/^ipp:\/\/127\.0\.0\.1:\d+\//);
  });

  test("switching the fake to toner empty changes the printer status on the next probe", async ({
    signedInPage: page,
  }) => {
    await page.goto("/printers");
    const card = page.getByRole("link", { name: /Office page printer/ });
    await expect(card).toBeVisible();
    const id = (await card.getAttribute("href"))!.split("/").pop()!;
    const status = async () => (await (await page.request.get(`/api/v1/printers/${id}/status`)).json()) as Record<string, unknown>;
    await expect.poll(async () => (await status()).printer_state ?? null, { timeout: 10_000 }).toBe("idle");

    await setPagePrinter(page, { printer_state: 5, reasons: ["toner-empty-error"] });
    await expect.poll(async () => (await status()).printer_state ?? null, { timeout: 10_000 }).toBe("stopped");

    // And back: two switches inside the 1 s probe interval's reach, which a 30 s interval cannot do.
    await resetPagePrinter(page);
    await expect.poll(async () => (await status()).printer_state ?? null, { timeout: 10_000 }).toBe("idle");
  });

  test("seeds the sheets with fixed codes and counts", async ({ signedInPage: page }) => {
    const get = async (code: string) => (await (await page.request.get(`/api/v1/sheets/${code}`)).json()) as Record<string, unknown>;
    const partly = await get(SEEDED_CODES.partlyUsed);
    expect(partly).toMatchObject({ code: SEEDED_CODES.partlyUsed, used: 17, state: "active" });
    expect(await get(SEEDED_CODES.full)).toMatchObject({ used: 48, total: 48, state: "active" });
    expect(await get(SEEDED_CODES.discarded)).toMatchObject({ state: "discarded" });
    const edge = await get(SEEDED_CODES.edge);
    expect(edge).toMatchObject({ used: 120, total: 189 });
    const purposes = (edge.cells as { purpose: string | null }[]).map((c) => c.purpose);
    expect(purposes).toHaveLength(120);
    expect(purposes.every((p) => p?.length === 120)).toBe(true);
    const custom = await (await page.request.get("/api/v1/sheet-types/e2e-custom-unknown-radius")).json();
    expect(JSON.stringify(custom)).toContain('"corner_radius":null');
  });

  test("the control body sets margins and cancel steps", async ({ signedInPage: page }) => {
    await setPagePrinter(page, { margins_hmm: 600, cancel_steps: 2 });
    const { state } = await pagePrinterControl(page);
    expect(state).toMatchObject({ margins_hmm: 600, cancel_steps: 2 });
    await resetPagePrinter(page);
    expect((await pagePrinterControl(page)).state).toMatchObject({ margins_hmm: 423, cancel_steps: 0 });
  });

  // The fake reports no paper size for its tray (`media-col-default`/`media-default` are missing), so the
  // hub rightly refuses a test page with 409 `media-unknown`. This spec proves what the UI does with the
  // real answer: the tray goes out in the request and the hub's own words come back next to the button.
  test("test print on a page printer sends the tray and shows the hub's refusal", async ({ signedInPage: page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/printers");
    await page.getByRole("link", { name: /Office page printer/ }).click();
    await page.getByRole("button", { name: "Test print" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("button", { name: /Tray/ })).toBeVisible();
    if (SHOTS) await page.screenshot({ path: `${SHOTS}/task-13-popover-1280-light.png`, fullPage: true });
    const request = page.waitForRequest((r) => r.url().endsWith("/test-print") && r.method() === "POST");
    await dialog.getByRole("button", { name: "Print test page" }).click();
    expect((await request).postDataJSON()).toEqual({ tray: "main-tray" });
    await expect(page.getByRole("alert").filter({ hasText: "neither the media" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Open the job" })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  });
});
