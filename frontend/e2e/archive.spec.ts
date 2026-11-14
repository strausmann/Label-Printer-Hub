import { mkdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
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
    // The written Close button at the end, not the × in the corner (both are named Close).
    await page.getByRole("dialog").getByRole("button", { name: "Close" }).filter({ hasText: "Close" }).click();
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
  test("worst-case vendor and product codes keep the feedback section inside the page and the link under 8000", async () => {
    const SHOTS = process.env.E2E_SHOTS_DIR;
    const key = "feedback-long-type";
    const geometry = {
      page_size: "A4", shape: "rectangle", cols: 2, rows: 5, label_w: 90, label_h: 50, pitch_x: 100, pitch_y: 55,
      margin_top: 10, margin_left: 5, corner_radius: null,
    };
    await setLanguage(page, "en");
    try {
      expect(
        await api(page, "POST", "/api/v1/sheet-types", {
          key,
          prefix: "FBL",
          vendor: "Ünïcödé Etikettenfabrik ".repeat(10).slice(0, 200),
          product_codes: Array.from({ length: 50 }, (_, i) => `CODE-${String(i).padStart(2, "0")}-${"Ü".repeat(30)}`),
          source_name: "A very long source name ".repeat(10).slice(0, 200),
          source_url: "http://wiki.intranet.local/labels",
          geometry,
        }),
      ).toBe(201);
      for (const [size, tag] of [[{ width: 1280, height: 800 }, "desktop"], [{ width: 390, height: 844 }, "phone"]] as const) {
        await page.setViewportSize(size);
        for (const scheme of ["light", "dark"] as const) {
          await page.emulateMedia({ colorScheme: scheme });
          await page.goto(`/sheets/archive?type=${key}`);
          const report = page.getByRole("link", { name: "Report a problem with the dimensions" });
          await expect(report).toBeVisible();
          expect(await noSideScroll(page)).toBe(true);
          const box = (await report.boundingBox())!;
          expect(box.x + box.width).toBeLessThanOrEqual(size.width);
          const href = (await report.getAttribute("href"))!;
          expect(href.length).toBeLessThanOrEqual(8000);
          expect(decodeURIComponent(href)).not.toContain("intranet");
          if (SHOTS) {
            mkdirSync(SHOTS, { recursive: true });
            await page.screenshot({ path: resolve(SHOTS, `task-18-long-${tag}-${scheme}.png`), fullPage: true });
          }
        }
      }
    } finally {
      await page.emulateMedia({ colorScheme: "light" });
      await api(page, "DELETE", `/api/v1/sheet-types/${key}`);
    }
  });

  test("feedback links open a pre-filled issue; the verify action is admin-only and asks first", async () => {
    const SHOTS = process.env.E2E_SHOTS_DIR;
    const shot = async (name: string) => {
      if (!SHOTS) return;
      mkdirSync(SHOTS, { recursive: true });
      await page.screenshot({ path: resolve(SHOTS, name), fullPage: true });
    };
    const key = "feedback-e2e-type";
    const geometry = {
      page_size: "A4", shape: "rectangle", cols: 2, rows: 5, label_w: 90, label_h: 50, pitch_x: 100, pitch_y: 55,
      margin_top: 10, margin_left: 5, corner_radius: null,
    };
    const verifiedOf = (k: string) =>
      page.evaluate(async (p) => ((await (await fetch(p)).json()) as { verified: boolean }).verified, `/api/v1/sheet-types/${k}`);
    const REPORT = "Report a problem with the dimensions";
    const CONFIRM = "Confirm the dimensions";
    const BASE = "https://github.com/strausmann/labelyard/issues/new?template=sheet-type-feedback.yml";
    await setLanguage(page, "en");
    await page.emulateMedia({ colorScheme: "light" });
    await page.setViewportSize({ width: 1280, height: 800 });
    try {
      expect(
        await api(page, "POST", "/api/v1/sheet-types", {
          key, prefix: "FBE", vendor: "Müller & Söhne", product_codes: ["FB-1", "FB#2"], source_name: "Our wiki",
          source_url: "http://wiki.intranet.local/labels", geometry,
        }),
      ).toBe(201);
      await page.goto(`/sheets/archive?type=${key}`);
      await expect(page.getByRole("heading", { name: key })).toBeVisible();

      // Both links, for the admin we are signed in as.
      const report = page.getByRole("link", { name: REPORT });
      const confirm = page.getByRole("link", { name: CONFIRM });
      for (const link of [report, confirm]) {
        expect(await link.getAttribute("href")).toMatch(new RegExp(`^${BASE.replace(/[?.]/g, "\\$&")}`));
        await expect(link).toHaveAttribute("target", "_blank");
        await expect(link).toHaveAttribute("rel", "noopener noreferrer");
      }
      const wrong = new URL((await report.getAttribute("href"))!).searchParams;
      expect(wrong.get("title")).toBe(`[sheet type] ${key} v1: dimensions wrong`);
      expect(wrong.get("vendor")).toBe("Müller & Söhne");
      expect(wrong.get("product_codes")).toBe("FB-1\nFB#2");
      // A custom type's source URL is user-entered and may point into an intranet: only the name travels.
      expect(wrong.get("provenance")).toBe("Our wiki");
      expect(await report.getAttribute("href")).not.toContain("intranet");
      expect(await report.getAttribute("href")).not.toContain(new URL(page.url()).host);
      expect(await noSideScroll(page)).toBe(true);

      for (const [size, tag] of [[{ width: 1280, height: 800 }, "desktop"], [{ width: 390, height: 844 }, "phone"]] as const) {
        await page.setViewportSize(size);
        for (const scheme of ["light", "dark"] as const) {
          await page.emulateMedia({ colorScheme: scheme });
          await expect(report).toBeVisible();
          expect(await noSideScroll(page)).toBe(true);
          await shot(`task-18-${tag}-${scheme}.png`);
        }
      }
      await page.emulateMedia({ colorScheme: "light" });
      await page.setViewportSize({ width: 1280, height: 800 });

      // A user below admin (the lowest the fixtures can be: the session answer is rewritten to "print").
      await page.route("**/api/v1/auth/session", async (route) => {
        const response = await route.fetch();
        if (route.request().method() !== "GET") return route.fulfill({ response });
        await route.fulfill({ response, json: { ...(await response.json()), scope: "print" } });
      });
      await page.goto(`/sheets/archive?type=${key}`);
      await expect(page.getByRole("link", { name: REPORT })).toBeVisible();
      await expect(page.getByRole("link", { name: CONFIRM })).toBeVisible();
      await expect(page.getByRole("button", { name: "Mark as verified locally" })).toHaveCount(0);
      await page.unroute("**/api/v1/auth/session");

      // The admin: nothing is sent until the dialog is confirmed.
      await page.goto(`/sheets/archive?type=${key}`);
      await page.getByRole("button", { name: "Mark as verified locally" }).click();
      const dialog = page.getByRole("alertdialog");
      await expect(dialog).toBeVisible();
      await shot("task-18-dialog-desktop.png");
      expect(await verifiedOf(key)).toBe(false);
      await dialog.getByRole("button", { name: "Cancel" }).click();
      await expect(dialog).toBeHidden();
      expect(await verifiedOf(key)).toBe(false);

      await page.getByRole("button", { name: "Mark as verified locally" }).click();
      await page.getByRole("alertdialog").getByRole("button", { name: "Mark as verified", exact: true }).click();
      await expect(page.getByRole("button", { name: "Mark as verified locally" })).toHaveCount(0);
      expect(await verifiedOf(key)).toBe(true);

      await setLanguage(page, "de");
      await page.goto(`/sheets/archive?type=${key}`);
      await expect(page.getByRole("link", { name: "Ein Problem mit den Maßen melden" })).toBeVisible();
      await setLanguage(page, "en");
    } finally {
      await page.unroute("**/api/v1/auth/session").catch(() => {});
      await api(page, "DELETE", `/api/v1/sheet-types/${key}`);
    }
  });
});
