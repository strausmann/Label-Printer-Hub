import { readFileSync } from "node:fs";
import type { Page } from "@playwright/test";
import { MAIN } from "./env";
import { expect, mainKey, signInWith, test } from "./fixtures";

const SEED = "avery-zweckform-l4736rev";
const noSideScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
const setLanguage = (page: Page, lang: "de" | "en") => page.evaluate((l) => localStorage.setItem("lph.lang", l), lang);

/** A write the way the page does it: session cookie plus the CSRF token of the session. */
async function api(page: Page, method: string, path: string, body?: unknown): Promise<number> {
  return page.evaluate(
    async ([m, p, b]) => {
      const session = await (await fetch("/api/v1/auth/session")).json();
      const response = await fetch(p as string, {
        method: m as string,
        headers: { "Content-Type": "application/json", "X-CSRF-Token": session.csrf_token },
        body: b === undefined ? undefined : JSON.stringify(b),
      });
      return response.status;
    },
    [method, path, body] as const,
  );
}

// One sign-in for the whole file: the hub limits sign-ins per minute.
test.describe.serial("sheet archive", () => {
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

  test("a seed type exported and imported back is reported as unchanged", async () => {
    const testInfo = test.info();
    await setLanguage(page, "en");
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto(`/sheets/archive?type=${SEED}`);
    await expect(page.getByRole("heading", { name: SEED })).toBeVisible();

    const download = page.waitForEvent("download");
    await page.getByRole("link", { name: "Export", exact: true }).click();
    const file = testInfo.outputPath("export.json");
    await (await download).saveAs(file);
    const doc = JSON.parse(readFileSync(file, "utf8"));
    expect(doc).toMatchObject({ format: "label-printer-hub.sheet-type", type: { key: SEED } });

    await page.getByRole("button", { name: "Import type" }).click();
    await page.getByRole("textbox", { name: "Export file contents" }).fill(readFileSync(file, "utf8"));
    await page.getByRole("button", { name: "Import", exact: true }).click();
    await expect(page.getByRole("status")).toHaveText(`Nothing changed: ${SEED} already has this geometry.`);
    await page.getByRole("button", { name: "Close" }).click();
  });

  test("importing a file with a wrong shape shows the server's complaint and keeps the dialog open", async () => {
    await page.goto("/sheets/archive");
    await page.getByRole("button", { name: "Import type" }).click();
    await page.getByRole("textbox", { name: "Export file contents" }).fill('{"format":"nope"}');
    await page.getByRole("button", { name: "Import", exact: true }).click();
    await expect(page.getByRole("alert")).toContainText("This is not a valid sheet type export.");
    await expect(page.getByRole("textbox", { name: "Export file contents" })).toBeVisible();
    await page.getByRole("button", { name: "Cancel" }).click();
  });

  for (const [lang, size] of [
    ["de", { width: 360, height: 780 }],
    ["en", { width: 1280, height: 800 }],
  ] as const) {
    for (const scheme of ["light", "dark"] as const) {
      test(`layout and screenshots, ${lang} at ${size.width} px, ${scheme}`, async () => {
    const testInfo = test.info();
        await setLanguage(page, lang);
        await page.emulateMedia({ colorScheme: scheme });
        await page.setViewportSize(size);
        const shot = async (name: string) =>
          page.screenshot({ path: testInfo.outputPath(`${name}-${size.width}-${lang}-${scheme}.png`), fullPage: true });

        await page.goto("/sheets/archive");
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
        const typeList = page.getByRole("list", { name: lang === "de" ? "Bogentypen" : "Sheet types" });
        await expect(typeList).toBeVisible();
        expect(await noSideScroll(page)).toBe(true);
        // The filters are folded on a phone (none is in use) and always open on a wide screen.
        const filters = page.locator("#archive-filters");
        const toggle = page.locator('button[aria-controls="archive-filters"]');
        if (size.width < 1024) {
          await expect(toggle).toBeVisible();
          await expect(filters).toBeHidden();
          await shot("list-folded");
          const first = typeList.getByRole("link").first();
          expect((await first.boundingBox())!.y).toBeLessThan(size.height);
          await toggle.click();
          await expect(filters).toBeVisible();
        } else {
          await expect(toggle).toBeHidden();
          await expect(filters).toBeVisible();
        }
        await shot("list");

        await page.goto(`/sheets/archive?type=${SEED}`);
        await expect(page.getByRole("heading", { name: SEED })).toBeVisible();
        await expect(page.getByRole("table")).toBeVisible();
        expect(await noSideScroll(page)).toBe(true);
        await shot("detail");

        // The form with the most fields.
        await page.getByRole("button", { name: lang === "de" ? "Maße bearbeiten" : "Edit geometry" }).click();
        await expect(page.getByRole("form")).toBeVisible();
        expect(await noSideScroll(page)).toBe(true);
        await shot("edit");
        await page.emulateMedia({ colorScheme: "light" });
      });
    }
  }

  test("worst-case data: long names, many versions, non-Latin text stay inside the page", async () => {
    const testInfo = test.info();
    await setLanguage(page, "en");
    await page.emulateMedia({ colorScheme: "light" });
    const key = `${"worst-case-".repeat(5)}type`.slice(0, 64).replace(/-$/, "x");
    const geometry = {
      page_size: "A4", shape: "rectangle", cols: 2, rows: 5, label_w: 90, label_h: 50, pitch_x: 100, pitch_y: 55,
      margin_top: 10, margin_left: 5, corner_radius: null,
    };
    try {
      expect(
        await api(page, "POST", "/api/v1/sheet-types", {
          key,
          prefix: "WORST",
          vendor: "Ünïcödé Etikettenfabrik ".repeat(8).slice(0, 200),
          description: "ラベル用紙 ".repeat(30).slice(0, 200),
          product_codes: Array.from({ length: 50 }, (_, i) => `CODE-${String(i).padStart(2, "0")}-${"X".repeat(30)}`),
          notes: "メモ ".repeat(300).slice(0, 2000),
          source_name: "A very long source name ".repeat(8).slice(0, 200),
          source_url: `https://example.invalid/${"path/".repeat(80)}`.slice(0, 500),
          geometry,
        }),
      ).toBe(201);
      for (let i = 1; i <= 11; i++) {
        expect(await api(page, "POST", `/api/v1/sheet-types/${key}/versions`, { geometry: { ...geometry, margin_top: 10 + i }, change_note: `Measured again, round ${i}: ${"very long note ".repeat(6)}` })).toBe(201);
      }
      for (const size of [{ width: 360, height: 780 }, { width: 1280, height: 800 }]) {
        await page.setViewportSize(size);
        await page.goto(`/sheets/archive?type=${key}`);
        await expect(page.getByRole("heading", { name: key })).toBeVisible();
        expect(await noSideScroll(page)).toBe(true);
        await page.screenshot({ path: testInfo.outputPath(`worst-${size.width}-en-light.png`), fullPage: true });
        await page.goto("/sheets/archive?q=worst");
        await expect(page.getByRole("link", { name: new RegExp(key) })).toBeVisible();
        expect(await noSideScroll(page)).toBe(true);
        await page.screenshot({ path: testInfo.outputPath(`worst-list-${size.width}-en-light.png`), fullPage: true });
      }
    } finally {
      await api(page, "DELETE", `/api/v1/sheet-types/${key}`);
    }
  });
});
