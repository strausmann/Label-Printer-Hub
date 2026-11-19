// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { mkdirSync } from "node:fs";
import type { Page } from "@playwright/test";
import { MAIN } from "./env";
import { expect, resetPagePrinter, setPagePrinter, test } from "./fixtures";

const SHOTS = process.env.E2E_SHOTS_DIR;
const noSideScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
const stack = (page: Page) => page.getByRole("region", { name: "Print status" });

async function tapePrinterState(page: Page, data: Record<string, unknown>) {
  const response = await page.request.post(`${MAIN.url}/__e2e/tape-printer/state`, { data });
  expect(response.ok(), await response.text()).toBe(true);
}

test.afterEach(async ({ page }) => {
  await resetPagePrinter(page);
  // The cover closed again and a fresh tape: the tape printers as the other tests expect them.
  const response = await page.request.post(`${MAIN.url}/__e2e/tape-printer/reset`);
  expect(response.ok(), await response.text()).toBe(true);
});

test.describe("print status notifications", () => {
  test("an item print reaches Done without a reload", async ({ signedInPage: page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/asset/42");
    await expect(page.getByRole("img", { name: "Label preview" })).toBeVisible();
    // A marker on the window: a reload would erase it.
    await page.evaluate(() => ((window as unknown as { __kept: boolean }).__kept = true));
    await page.getByRole("button", { name: "Print now" }).click();
    await expect(stack(page).getByText(/^Label/)).toBeVisible();
    await expect(stack(page).getByText("Done", { exact: true })).toBeVisible({ timeout: 30_000 });
    expect(await page.evaluate(() => (window as unknown as { __kept?: boolean }).__kept)).toBe(true);
    // It leaves by itself.
    await expect(stack(page).getByRole("listitem")).toHaveCount(0, { timeout: 15_000 });
  });

  test("an open cover is a warning in words and goes when it closes (#376)", async ({ signedInPage: page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await tapePrinterState(page, { door_open: true });
    await page.goto("/");
    const attention = page.getByRole("region", { name: "Needs attention" });
    const entry = attention.getByRole("listitem").filter({ hasText: "Bench PT-P750W" }).filter({ hasText: "Cover open — close it to print" });
    // The polled printer reports the open cover within a probe or two: a warning (diamond) while nothing waits.
    await expect(entry).toBeVisible({ timeout: 15_000 });
    await expect(entry.locator('[data-shape="diamond"]')).toHaveCount(1);
    await expect(page.getByText("doorOpen")).toHaveCount(0);

    // A print to it is refused: the entry turns into a problem at once (the refusal lives in the tab, so the
    // way back to the overview is a click, not a reload).
    const printers = (await (await page.request.get("/api/v1/printers")).json()) as Array<{ id: string; name: string }>;
    const bench = printers.find((p) => p.name === "Bench PT-P750W")!.id;
    await page.evaluate((id) => localStorage.setItem("lph.printer", id), bench);
    await page.goto("/asset/42");
    await expect(page.getByRole("img", { name: "Label preview" })).toBeVisible();
    await page.getByRole("button", { name: "Print now" }).click();
    await expect(page.getByRole("alert")).toBeVisible({ timeout: 15_000 });
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Overview" }).click();
    await expect(entry.getByText("A print was refused")).toBeVisible();
    await expect(entry.locator('[data-shape="dot"]')).toHaveCount(1);

    // The cover closes: the entry goes after the next status event, without Dismiss.
    await tapePrinterState(page, { door_open: false });
    await expect(attention.getByRole("listitem").filter({ hasText: "Bench PT-P750W" }).filter({ hasText: "Cover open — close it to print" })).toHaveCount(0, {
      timeout: 15_000,
    });
  });

  test("a page-printer test print keeps updating while the user moves to another page", async ({ signedInPage: page }) => {
    await setPagePrinter(page, { job_script: [3, 5, 9] });
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/printers");
    await page.getByRole("link", { name: /Office page printer/ }).click();
    await page.evaluate(() => ((window as unknown as { __kept: boolean }).__kept = true));
    await page.getByRole("button", { name: "Test print" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Print test page" }).click();
    await expect(stack(page).getByText(/^Test print/)).toBeVisible();
    // Away from the printer while the job is still at the printer.
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Jobs" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Jobs" })).toBeVisible();
    await expect(stack(page).getByText(/^Test print/)).toBeVisible();
    await expect(stack(page).getByText("Done", { exact: true })).toBeVisible({ timeout: 45_000 });
    expect(await page.evaluate(() => (window as unknown as { __kept?: boolean }).__kept)).toBe(true);
    expect(await noSideScroll(page)).toBe(true);
  });

  test("screenshots: a failed print stays, with its error and a way out", async ({ signedInPage: page }) => {
    test.skip(!SHOTS, "screenshots are an artifact, taken only with E2E_SHOTS_DIR");
    mkdirSync(SHOTS!, { recursive: true });
    test.setTimeout(150_000);
    for (const scheme of ["light", "dark"] as const) {
      await page.emulateMedia({ colorScheme: scheme });
      for (const [width, height] of [
        [1280, 800],
        [390, 844],
      ] as const) {
        // IPP job-state 8 = aborted: the hub marks the job failed.
        await setPagePrinter(page, { job_script: [3, 8] });
        await page.setViewportSize({ width, height });
        await page.goto("/printers");
        await page.getByRole("link", { name: /Office page printer/ }).click();
        await page.getByRole("button", { name: "Test print" }).click();
        await page.getByRole("dialog").getByRole("button", { name: "Print test page" }).click();
        await expect(stack(page).getByText("Failed", { exact: true })).toBeVisible({ timeout: 30_000 });
        await expect(stack(page).getByRole("link", { name: "Open the job" })).toBeVisible();
        await page.screenshot({ path: `${SHOTS}/task-19a-failed-${width}-${scheme}.png` });
        expect(await noSideScroll(page)).toBe(true);
        await stack(page).getByRole("button", { name: "Dismiss notification" }).first().click();
        await resetPagePrinter(page);
      }
    }
  });

  test("screenshots: five failed prints stay bounded on a phone, Close and Retry reachable", async ({ signedInPage: page }) => {
    test.skip(!SHOTS, "screenshots are an artifact, taken only with E2E_SHOTS_DIR");
    mkdirSync(SHOTS!, { recursive: true });
    test.setTimeout(160_000);
    await page.setViewportSize({ width: 390, height: 844 });
    await setPagePrinter(page, { job_script: [8] });
    await page.goto("/printers");
    await page.getByRole("link", { name: /Office page printer/ }).click();
    for (let n = 1; n <= 5; n++) {
      await page.getByRole("button", { name: "Test print" }).click();
      await page.getByRole("dialog").getByRole("button", { name: "Print test page" }).click();
      await expect(stack(page).getByText("Failed", { exact: true })).toHaveCount(Math.min(n, 3), { timeout: 30_000 });
      await expect(page.getByRole("dialog")).toHaveCount(0);
    }
    await expect(stack(page).getByText("2 more print notifications")).toBeVisible();
    // The stack stays inside the screen, above the tab bar, and the topmost Close button is on screen.
    const box = await stack(page).boundingBox();
    expect(box!.y).toBeGreaterThanOrEqual(0);
    expect(box!.y + box!.height).toBeLessThanOrEqual(844);
    const close = stack(page).getByRole("button", { name: "Dismiss notification" }).first();
    await close.scrollIntoViewIfNeeded();
    await expect(close).toBeInViewport();
    for (const scheme of ["light", "dark"] as const) {
      await page.emulateMedia({ colorScheme: scheme });
      await page.screenshot({ path: `${SHOTS}/task-19a-five-failed-390-${scheme}.png` });
    }
    expect(await noSideScroll(page)).toBe(true);
    await resetPagePrinter(page);
  });

  test("screenshots: the stack in light and dark, desktop and phone", async({ signedInPage: page }) => {
    test.skip(!SHOTS, "screenshots are an artifact, taken only with E2E_SHOTS_DIR");
    // Four rounds, each waits for the fake printer's queue to empty again.
    test.setTimeout(150_000);
    mkdirSync(SHOTS!, { recursive: true });
    for (const scheme of ["light", "dark"] as const) {
      await page.emulateMedia({ colorScheme: scheme });
      for (const [width, height] of [
        [1280, 800],
        [390, 844],
      ] as const) {
        await setPagePrinter(page, { job_script: [3, 3, 3, 3, 3, 3, 3, 9] });
        await page.setViewportSize({ width, height });
        await page.goto("/printers");
        await page.getByRole("link", { name: /Office page printer/ }).click();
        await page.getByRole("button", { name: "Test print" }).click();
        await page.getByRole("dialog").getByRole("button", { name: "Print test page" }).click();
        await expect(stack(page).getByText(/^Test print/)).toBeVisible();
        await page.screenshot({ path: `${SHOTS}/task-19a-stack-${width}-${scheme}.png` });
        expect(await noSideScroll(page)).toBe(true);
        await page.getByRole("button", { name: "Dismiss notification" }).first().click();
        await resetPagePrinter(page);
      }
    }
  });
});
