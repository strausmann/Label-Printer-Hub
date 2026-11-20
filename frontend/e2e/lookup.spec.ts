// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import type { Page } from "@playwright/test";
import { expect, test } from "./fixtures";

const SHOTS = process.env.E2E_SHOTS_DIR;
const shot = async (page: Page, name: string) => {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: resolve(SHOTS, name), fullPage: true });
};
const noSideScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);

type PrinterRow = { id: string; slug: string; name: string };

/** A write the way the page does it: session cookie plus the CSRF token of the session. */
async function putDefaults(page: Page, slug: string, layout_defaults: Record<string, unknown>): Promise<void> {
  const session = (await (await page.request.get("/api/v1/auth/session")).json()) as { csrf_token: string };
  const response = await page.request.put(`/api/v1/admin/printers/${slug}`, {
    headers: { "X-CSRF-Token": session.csrf_token },
    data: { layout_defaults },
  });
  expect(response.ok(), await response.text()).toBe(true);
}

test.describe("lookup", () => {
  test("opening /asset/<id> shows the item and prints it", async ({ signedInPage: page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/asset/42");
    await expect(page.getByRole("heading", { level: 1, name: "Snipe-IT item" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Open in Snipe-IT" })).toHaveAttribute("href", "https://example.invalid/snipeit/42");
    const preview = page.getByRole("img", { name: "Label preview" });
    await expect(preview).toBeVisible();
    // The preview is a real picture from the layout engine, not a broken image.
    expect(await preview.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0)).toBe(true);
    await shot(page, "task-12-item-desktop.png");

    await page.getByRole("button", { name: "Print now" }).click();
    await expect(page.getByText(/Sent to Workshop PT-P750W/)).toBeVisible();
    await page.getByRole("link", { name: "View the job" }).click();
    await expect(page).toHaveURL(/\/jobs\/[0-9a-f-]{36}$/);
    await expect(page.getByRole("heading", { level: 1, name: "Snipe-IT item" })).toBeVisible();

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/spool/7");
    await expect(page.getByRole("heading", { level: 1, name: "Spoolman item" })).toBeVisible();
    // On the P-touch a Spoolman item starts on the default layout, not the spool label (#346).
    await expect(page.getByRole("combobox", { name: "Layout" })).toHaveValue("qr_two_lines");
    await expect(page.getByRole("img", { name: "Label preview" })).toBeVisible();
    await shot(page, "task-12-item-phone.png");
    expect(await noSideScroll(page)).toBe(true);
  });

  test("the cart collects items from QR paths and prints them as one batch", async ({ signedInPage: page }) => {
    await page.goto("/product/3");
    await page.getByRole("region", { name: "Print", exact: true }).getByRole("button", { name: "Add to cart" }).click();
    await page.goto("/loc/5");
    await page.getByRole("region", { name: "Print", exact: true }).getByRole("button", { name: "Add to cart" }).click();
    await page.getByRole("link", { name: "Cart (2)" }).click();
    await expect(page.getByRole("list", { name: "Cart" }).getByRole("listitem")).toHaveCount(2);

    // A reload keeps the cart (it lives in this browser).
    await page.reload();
    await expect(page.getByRole("list", { name: "Cart" }).getByRole("listitem")).toHaveCount(2);

    await page.getByRole("button", { name: "Print 2 labels" }).click();
    await expect(page.getByText(/2 labels sent to Workshop PT-P750W/)).toBeVisible();
    await expect(page.getByText("The cart is empty.")).toBeVisible();
  });

  test("the item's sheet section adds to the cart and the cart opens with that sheet", async ({ signedInPage: page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/");
    const printers = (await (await page.request.get("/api/v1/printers")).json()) as { id: string; name: string }[];
    const pagePrinter = printers.find((p) => p.name === "Office page printer")!;
    await page.evaluate((id) => {
      localStorage.setItem("lph.printer", id);
      localStorage.removeItem("lph.cart");
    }, pagePrinter.id);
    try {
      await page.goto("/lookup/grocy/7");
      const section = page.getByRole("region", { name: "Print onto a sheet" });
      await expect(section).toBeVisible();
      // The test only adds to the cart; it assumes the sheet has no free cells to fill, other specs use it too.
      // The field starts on the type earlier specs left as the default (print-sheet, calibration), and opening it then lists only
      // what matches that text: type what is wanted instead of assuming which type it starts on.
      const typeField = section.getByRole("combobox", { name: "Sheet type" });
      await typeField.fill("L4736");
      await page.getByRole("option", { name: /L4736/ }).first().click();
      const sheet = section.getByRole("combobox", { name: "Sheet", exact: true });
      await sheet.click();
      await page.getByRole("option", { name: /L4736-0001/ }).click();
      await expect(sheet).toHaveValue("L4736-0001");
      const trayButton = section.getByRole("button", { name: /Tray/ });
      const trayLabel = ((await trayButton.textContent()) ?? "").replace("Tray", "").trim();
      expect(trayLabel).not.toBe("");
      const add = section.getByRole("button", { name: "Add to cart" });
      await expect(add).toBeEnabled();
      await add.click();
      await expect(page.locator("header").getByRole("link", { name: /^Cart, 1 item/ })).toBeVisible();
      await section.getByRole("link", { name: "Open cart" }).click();
      await expect(page).toHaveURL(/\/cart\?sheet=L4736-0001&tray=[^&]+$/);
      await expect(page.getByRole("region", { name: "Print onto a sheet" }).getByRole("button", { name: /Tray/ })).toContainText(trayLabel);
      await expect(page.getByRole("region", { name: "Print onto a sheet" }).getByRole("combobox", { name: "Sheet", exact: true })).toHaveValue("L4736-0001");
    } finally {
      // Net zero: the entry leaves the cart again and the printer choice is reset.
      await page.evaluate((id) => {
        localStorage.removeItem("lph.cart");
        localStorage.removeItem("lph.printer");
        localStorage.removeItem(`lph.sheetType.${id}`);
      }, pagePrinter.id);
    }
  });

  // The status is served from the test (the service worker would answer the route first).
  test.describe("with a QL printer", () => {
    test.use({ serviceWorkers: "block" });
    test("the cart flags an item whose QR code is too long", async ({ signedInPage: page }) => {
      const printers = (await (await page.request.get("/api/v1/printers")).json()) as { id: string; name: string }[];
      const ql = printers.find((p) => p.name === "Office QL-820NWB")!;
      // The hub's mock QL is unpolled, so the test serves its status: 62 mm tape loaded.
      await page.route(new RegExp(`/api/v1/printers/${ql.id}/status$`), async (route) => {
        const response = await route.fetch();
        const body = (await response.json()) as Record<string, unknown>;
        Object.assign(body, { online: true, polled: true, stale: false, tape_loaded: "62mm", tape_width_mm: 62, last_probe_age_s: 3, note: null });
        await route.fulfill({ response, json: body });
      });
      // The fixture lookup builds the link from the identifier, so a long identifier is a link the QR code cannot hold (the route takes identifiers up to 256 characters).
      const long = "a".repeat(250);
      await page.evaluate(
        ([printer, id]) => {
          localStorage.setItem("lph.printer", printer!);
          localStorage.setItem(
            "lph.cart",
            JSON.stringify([
              { app: "snipeit", id: "42", name: "Short link", content_type: "qr_two_lines", copies: 1 },
              { app: "snipeit", id: id!, name: "Long link", content_type: "qr_two_lines", copies: 1 },
            ]),
          );
        },
        [ql.id, long],
      );
      await page.goto("/cart");
      const rows = page.getByRole("list", { name: "Cart" }).getByRole("listitem");
      await expect(rows).toHaveCount(2);
      await expect(rows.nth(1)).toContainText(/The QR code does not fit this tape: \d+ of at most \d+ bytes\./);
      await expect(rows.nth(0)).not.toContainText("does not fit");
      await expect(page.getByText("1 item will not print.")).toBeVisible();
      // The flag warns, it does not forbid: the print button stays usable.
      await expect(page.getByRole("button", { name: "Print 2 labels" })).toBeEnabled();
      await shot(page, "task-12-cart-flag.png");
    });
  });
});


// #346: the swatch-style spool label on the QL fixture printer (its mock holds 62 mm endless). The hub does not poll
// the mock QL, so the test serves its status with 62 mm loaded, as ql-layout.spec.ts does.
test.describe("the Spoolman spool label", () => {
  test.use({ serviceWorkers: "block" });
  let id = "";
  let slug = "office-ql";

  test.beforeEach(async ({ signedInPage: page }) => {
    const printers = (await (await page.request.get("/api/v1/printers")).json()) as PrinterRow[];
    ({ id, slug } = printers.find((p) => p.name === "Office QL-820NWB")!);
    await putDefaults(page, slug, {});
    await page.route(new RegExp(`/api/v1/printers/${id}/status$`), async (route) => {
      const response = await route.fetch();
      const body = (await response.json()) as Record<string, unknown>;
      Object.assign(body, { online: true, polled: true, stale: false, tape_loaded: "62mm", tape_width_mm: 62, last_probe_age_s: 3, note: null });
      await route.fulfill({ response, json: body });
    });
    await page.evaluate((printer) => localStorage.setItem("lph.printer", printer), id);
  });
  test.afterEach(async ({ signedInPage: page }) => {
    await putDefaults(page, slug, {});
    await page.evaluate(() => localStorage.removeItem("lph.printer"));
  });

  test("a Spoolman spool previews and prints the spool label on the QL", async ({ signedInPage: page }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto("/spool/12");
    await expect(page.getByRole("heading", { level: 1, name: "Spoolman item" })).toBeVisible();
    await expect(page.getByRole("combobox", { name: "Layout" })).toHaveValue("spool_swatch");
    await expect(page.getByRole("combobox", { name: "Layout" }).locator("option:checked")).toHaveText("Spool label");
    await expect(page.getByRole("radiogroup", { name: "Direction" })).toHaveCount(0);
    const preview = page.getByRole("img", { name: "Label preview" });
    await expect.poll(() => preview.evaluate((img: HTMLImageElement) => img.complete && [img.naturalWidth, img.naturalHeight].join("x"))).toBe("696x425");
    await shot(page, "t15h-spool-label-1280.png");

    const response = page.waitForResponse((r) => r.url().includes(`/api/v1/print/${id}/batch`));
    await page.getByRole("button", { name: "Print now" }).click();
    const accepted = (await (await response).json()) as { job_ids: string[] };
    const job = (await (await page.request.get(`/api/v1/jobs/${accepted.job_ids[0]}`)).json()) as { payload?: Record<string, unknown>; content_type?: string; options?: Record<string, unknown> };
    const payload = (job.payload ?? job) as { content_type?: string; options?: { orientation?: string } };
    expect(payload.content_type).toBe("spool_swatch");
    expect(payload.options?.orientation).toBe("across");

    await page.setViewportSize({ width: 390, height: 844 });
    await page.reload();
    await expect.poll(() => preview.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth)).toBe(696);
    await shot(page, "t15h-spool-label-390.png");
    expect(await noSideScroll(page)).toBe(true);
  });

  test("a stored along default does not change the spool label", async ({ signedInPage: page }) => {
    await putDefaults(page, slug, { "62": { orientation: "along" } });
    await page.setViewportSize({ width: 1280, height: 900 });
    const requests: Record<string, unknown>[] = [];
    page.on("request", (r) => {
      if (r.url().endsWith("/api/v1/render/preview") && r.method() === "POST") requests.push(r.postDataJSON() as Record<string, unknown>);
    });
    await page.goto("/spool/12");
    const preview = page.getByRole("img", { name: "Label preview" });
    await expect.poll(() => preview.evaluate((img: HTMLImageElement) => img.complete && [img.naturalWidth, img.naturalHeight].join("x"))).toBe("696x425");
    expect(requests.length).toBeGreaterThan(0);
    for (const body of requests) {
      expect(body).not.toHaveProperty("orientation");
      expect(body).not.toHaveProperty("layout_preset");
    }
  });
});
