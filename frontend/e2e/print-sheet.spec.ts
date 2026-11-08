import type { Page } from "@playwright/test";
import { MAIN } from "./env";
import { expect, mainKey, resetPagePrinter, setPagePrinter, signInWith, test } from "./fixtures";

// Seed data (creation order is fixed, see `backend/tests/e2e_app.py`).
const PARTLY_USED = "L4736-0001";
const FULL = "L4736-0002";
const DISCARDED = "L4736-0003";
const EDGE = "L4731-0001"; // 189 cells, 120 used, purposes of 120 characters

const noSideScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth);
const setLanguage = (page: Page, lang: "de" | "en") => page.evaluate((l) => localStorage.setItem("lph.lang", l), lang);

/** The cart holds `copies` Grocy labels and the page printer is the chosen one; then the cart page opens. */
async function openCart(page: Page, path: string, copies: number) {
  const printers = (await (await page.request.get("/api/printers")).json()) as Array<{ id: string; name: string }>;
  const printerId = printers.find((p) => p.name === "Office page printer")!.id;
  await page.goto("/");
  await page.evaluate(
    ([id, n]) => {
      localStorage.setItem("lph.printer", String(id));
      localStorage.setItem("lph.cart", JSON.stringify([{ app: "grocy", id: "7", name: "Flour", content_type: "qr_two_lines", copies: n }]));
    },
    [printerId, copies] as const,
  );
  await page.goto(path);
}

const sheetUsed = async (page: Page, code: string) => ((await (await page.request.get(`/api/sheets/${code}`)).json()) as { used: number }).used;

// One sign-in for the whole file: the hub limits sign-ins per minute.
test.describe.serial("print onto a sheet", () => {
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
  test.afterEach(async () => {
    await resetPagePrinter(page);
  });

  test("prints nine Grocy items onto the partly used sheet; the sheet then shows nine more cells, from Grocy", async () => {
    await setLanguage(page, "en");
    await page.setViewportSize({ width: 1280, height: 800 });
    // The fake printer takes the job: pending, processing, completed.
    await setPagePrinter(page, { job_script: [3, 5, 9] });
    const before = await sheetUsed(page, PARTLY_USED);

    await openCart(page, `/cart?sheet=${PARTLY_USED}`, 9);
    await expect(page.getByRole("heading", { level: 2, name: "Print onto a sheet" })).toBeVisible();
    await expect(page.getByRole("combobox", { name: "Sheet" })).toHaveValue(PARTLY_USED);
    await expect(page.getByText("9 printed now")).toBeVisible({ timeout: 30_000 });
    expect(await noSideScroll(page)).toBe(true);

    const print = page.getByRole("button", { name: "Print onto sheet" });
    await expect(print).toBeEnabled();
    await print.click();
    const sent = page.getByRole("status", { name: "Sent to the print queue" });
    await expect(sent).toBeVisible();
    await expect(sent.getByRole("link", { name: /View job/ })).toHaveCount(1);
    // The hub accepted it: the cart is empty now, the result stays.
    expect(await page.evaluate(() => localStorage.getItem("lph.cart"))).toBe("[]");

    // The cells stay reserved until the printer reports the job done.
    await expect.poll(() => sheetUsed(page, PARTLY_USED), { timeout: 40_000, intervals: [1000] }).toBe(before + 9);

    await page.goto(`/sheets/${PARTLY_USED}`);
    await expect(page.getByText(`${before + 9} of 48 used`)).toBeVisible();
    const cells = page.getByRole("list", { name: "Cells in use" });
    await expect(cells.getByRole("listitem").filter({ hasText: "· Grocy" })).toHaveCount(9);
    await expect(cells.getByRole("listitem").filter({ hasText: "· marked by hand" }).first()).toBeVisible();
  });

  test("a sheet in the link that is discarded or full is explained, and the cart keeps its labels", async () => {
    await setLanguage(page, "en");
    await page.setViewportSize({ width: 1280, height: 800 });
    await openCart(page, `/cart?sheet=${DISCARDED}`, 2);
    await expect(page.getByText(`${DISCARDED} is discarded and cannot take labels any more.`)).toBeVisible();
    await page.goto(`/cart?sheet=${FULL}`);
    await expect(page.getByText(`${FULL} has no free cell left.`)).toBeVisible();
    // Nothing was sent: the cart keeps its labels.
    expect(await page.evaluate(() => JSON.parse(localStorage.getItem("lph.cart") ?? "[]").length)).toBe(1);
  });

  test("with an empty cart the link says what to do", async () => {
    await setLanguage(page, "en");
    await page.goto("/");
    await page.evaluate(() => localStorage.setItem("lph.cart", "[]"));
    await page.goto(`/cart?sheet=${PARTLY_USED}`);
    await expect(page.getByText(`Add items to print onto ${PARTLY_USED}.`)).toBeVisible();
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
        const heading = de ? "Auf einen Bogen drucken" : "Print onto a sheet";

        // The 189-cell sheet with 120 used cells and ten labels.
        await openCart(page, `/cart?sheet=${EDGE}`, 10);
        await expect(page.getByRole("heading", { level: 2, name: heading })).toBeVisible();
        await expect(page.getByText(de ? "10 jetzt gedruckt" : "10 printed now")).toBeVisible({ timeout: 30_000 });
        expect(await noSideScroll(page)).toBe(true);
        await shot("cart-edge");

        // A stopped printer: the alert, the reason in words, and the button that queues.
        await setPagePrinter(page, { printer_state: 5, reasons: ["toner-empty-error"] });
        const queue = page.getByRole("button", { name: de ? "In die Druckwarteschlange legen" : "Add to print queue" });
        await expect(queue).toBeVisible({ timeout: 15_000 });
        await expect(page.getByRole("alert").filter({ hasText: de ? "Toner leer" : "toner empty" })).toBeVisible();
        expect(await noSideScroll(page)).toBe(true);
        await shot("cart-stopped");
        await resetPagePrinter(page);

        // The item view of a page printer has the sheet section instead of the tape preview.
        await page.goto("/lookup/grocy/7");
        await expect(page.getByRole("heading", { level: 2, name: heading })).toBeVisible();
        await expect(page.getByRole("img", { name: de ? "Etikettenvorschau" : "Label preview" })).toHaveCount(0);
        expect(await noSideScroll(page)).toBe(true);
        await shot("item");

        // A tape printer keeps the tape preview.
        const printers = (await (await page.request.get("/api/printers")).json()) as Array<{ id: string; name: string }>;
        await page.evaluate((id) => localStorage.setItem("lph.printer", id), printers.find((p) => p.name === "Workshop PT-P750W")!.id);
        await page.goto("/lookup/grocy/7");
        await expect(page.getByRole("heading", { level: 2, name: heading })).toHaveCount(0);
        await expect(page.getByRole("button", { name: de ? "Jetzt drucken" : "Print now" })).toBeVisible();
        await page.emulateMedia({ colorScheme: "light" });
      });
    }
  }
});
