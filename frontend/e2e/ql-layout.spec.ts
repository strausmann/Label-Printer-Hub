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
/** The radio input is visually hidden; a person presses its segment (the label around it). */
const pick = (page: Page, name: string) => page.locator("label", { has: page.getByRole("radio", { name, exact: true }) }).click();
const noSideScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);

type PrinterRow = { id: string; slug: string; name: string; layout_defaults?: Record<string, { orientation?: string | null; preset?: string | null }> };

/** A write the way the page does it: session cookie plus the CSRF token of the session. */
async function putDefaults(page: Page, slug: string, layout_defaults: Record<string, unknown>): Promise<void> {
  const session = (await (await page.request.get("/api/v1/auth/session")).json()) as { csrf_token: string };
  const response = await page.request.put(`/api/v1/admin/printers/${slug}`, {
    headers: { "X-CSRF-Token": session.csrf_token },
    data: { layout_defaults },
  });
  expect(response.ok(), await response.text()).toBe(true);
}

// The hub's mock QL is unpolled, so the test serves its status (62 mm loaded). The preview is the real layout engine.
test.describe("QL 62 mm layout choice", () => {
  test.use({ serviceWorkers: "block" });
  let id = "";
  let slug = "office-ql";

  test.beforeEach(async ({ signedInPage: page }) => {
    const printers = (await (await page.request.get("/api/v1/printers")).json()) as PrinterRow[];
    const ql = printers.find((p) => p.name === "Office QL-820NWB")!;
    ({ id, slug } = ql);
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
  });

  test("the choice drives a real preview and the job request", async ({ signedInPage: page }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto("/asset/42");
    await expect(page.getByRole("radio", { name: "Compact" })).toBeChecked();
    const preview = page.getByRole("img", { name: "Label preview" });
    // Across at real pixel scale: 696 px = 62 mm at 300 dpi.
    await expect.poll(() => preview.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth)).toBe(696);
    await expect(preview).toHaveCSS("image-rendering", "pixelated");
    await shot(page, "task-21b-item-1280-light.png");

    await pick(page, "Along");
    // Along is the landscape band before the printer rotates it: 696 px high.
    await expect.poll(() => preview.evaluate((img: HTMLImageElement) => img.naturalHeight)).toBe(696);
    await expect(page.getByRole("radiogroup", { name: "Arrangement" })).toHaveCount(0);

    const request = page.waitForRequest((r) => r.url().includes(`/api/v1/print/${id}/batch`));
    await page.getByRole("button", { name: "Print now" }).click();
    const options = ((await request).postDataJSON() as { items: { options: Record<string, unknown> }[] }).items[0]!.options;
    expect(options).toEqual({ copies: 1, orientation: "along" });
  });

  test("the printer's stored default is preselected and saved from the printer settings", async ({ signedInPage: page }) => {
    await page.goto("/settings/printers");
    await page.getByRole("button", { name: "Edit Office QL-820NWB" }).click();
    await expect(page.getByRole("switch", { name: "Half cut by default" })).toHaveCount(0);
    await pick(page, "Standard");
    await shot(page, "task-21b-admin-1280-light.png");
    await page.getByRole("button", { name: "Save printer" }).click();
    await expect(page.getByRole("form", { name: /Edit Office QL-820NWB/ })).toHaveCount(0);

    const printers = (await (await page.request.get("/api/v1/printers")).json()) as PrinterRow[];
    expect(printers.find((p) => p.id === id)!.layout_defaults?.["62"]).toMatchObject({ orientation: "across", preset: "standard" });

    await page.goto("/asset/42");
    await expect(page.getByRole("radio", { name: "Standard" })).toBeChecked();
    const preview = page.getByRole("img", { name: "Label preview" });
    await expect.poll(() => preview.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth)).toBe(696);
  });

  test("the P-touch printer's print panel has no choice and its form keeps the half cut", async ({ signedInPage: page }) => {
    const printers = (await (await page.request.get("/api/v1/printers")).json()) as PrinterRow[];
    await page.evaluate((printer) => localStorage.setItem("lph.printer", printer), printers.find((p) => p.name === "Workshop PT-P750W")!.id);
    await page.goto("/asset/42");
    await expect(page.getByRole("button", { name: "Print now" })).toBeVisible();
    await expect(page.getByRole("radiogroup", { name: "Direction" })).toHaveCount(0);
    await page.goto("/settings/printers");
    await page.getByRole("button", { name: "Edit Workshop PT-P750W" }).click();
    await expect(page.getByRole("switch", { name: "Half cut by default" })).toBeVisible();
  });

  const scenes = [
    { width: 1280, height: 900, scheme: "light" },
    { width: 1280, height: 900, scheme: "dark" },
    { width: 390, height: 844, scheme: "light" },
    { width: 390, height: 844, scheme: "dark" },
  ] as const;
  for (const { width, height, scheme } of scenes) {
    test(`screens at ${width} px, ${scheme}`, async ({ signedInPage: page }) => {
      await page.setViewportSize({ width, height });
      await page.emulateMedia({ colorScheme: scheme });
      await page.goto("/asset/42");
      await expect(page.getByRole("radio", { name: "Compact" })).toBeChecked();
      await expect(page.getByRole("img", { name: "Label preview" })).toBeVisible();
      expect(await noSideScroll(page)).toBe(true);
      // 44 px targets on a phone.
      const box = await page.getByRole("radio", { name: "Compact" }).locator("xpath=ancestor::label").boundingBox();
      expect(box!.height).toBeGreaterThanOrEqual(44);
      await shot(page, `task-21b-item-${width}-${scheme}.png`);
      await page.getByRole("button", { name: "Add to cart" }).click();
      await page.goto("/cart");
      await expect(page.getByRole("radio", { name: "Compact" })).toBeChecked();
      await expect(page.getByRole("img", { name: "Label preview" })).toBeVisible();
      expect(await noSideScroll(page)).toBe(true);
      await shot(page, `task-21b-cart-${width}-${scheme}.png`);
      await page.getByRole("button", { name: "Empty the cart" }).click();
      await page.goto("/settings/printers");
      await page.getByRole("button", { name: "Edit Office QL-820NWB" }).click();
      await expect(page.getByRole("radio", { name: "Compact" })).toBeChecked();
      expect(await noSideScroll(page)).toBe(true);
      await shot(page, `task-21b-admin-${width}-${scheme}.png`);
    });
  }
});
