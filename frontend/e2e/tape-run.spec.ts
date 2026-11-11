import { mkdirSync } from "node:fs";
import type { Page } from "@playwright/test";
import { MAIN } from "./env";
import { expect, test } from "./fixtures";

/*
 * #277: a tape batch of more than 50 labels prints in parts; the next part waits for the user. When the tape
 * runs out inside a part, the stack names the labels to count and reprints from the one the user picks.
 * The tape printers are the hub's in-memory backend; `/__e2e/tape-printer/state` lets their tape run out.
 */

const SHOTS = process.env.E2E_SHOTS_DIR;
const stack = (page: Page) => page.getByRole("region", { name: "Print status" });
/** The state line of a finished batch card: "Done · 51 of 51 items · Part 2 of 2". */
const done = (page: Page) => stack(page).getByText(/^Done ·/);
const noSideScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);

async function tapeOutIn(page: Page, labels: number) {
  const response = await page.request.post(`${MAIN.url}/__e2e/tape-printer/state`, { data: { tape_runs_out_in: labels } });
  expect(response.ok(), await response.text()).toBe(true);
}
async function newTape(page: Page) {
  const response = await page.request.post(`${MAIN.url}/__e2e/tape-printer/reset`);
  expect(response.ok(), await response.text()).toBe(true);
}

/** The cart holds `labels` Snipe-IT labels for the workshop PT printer; then the cart page opens. */
async function cartOf(page: Page, labels: number) {
  const printers = (await (await page.request.get("/api/v1/printers")).json()) as Array<{ id: string; name: string }>;
  const printerId = printers.find((p) => p.name === "Workshop PT-P750W")!.id;
  await page.goto("/");
  await page.evaluate(
    ([id, n]) => {
      localStorage.setItem("lph.printer", String(id));
      const lines = Array.from({ length: Math.ceil(n / 10) }, (_, i) => ({ app: "snipeit", id: String(500 + i), name: `Asset ${500 + i}`, content_type: "qr_two_lines", copies: Math.min(10, n - i * 10) }));
      localStorage.setItem("lph.cart", JSON.stringify(lines));
    },
    [printerId, labels] as const,
  );
  await page.goto("/cart");
}

/**
 * Held runs live in the hub's queue for the whole e2e session, not per test: a job another spec
 * retried on a mock printer that refuses it stays as a stopped run ("Tape prints that wait for
 * you"). The tests here start from an empty list, so they only ever see their own run.
 */
async function discardHeldRuns(page: Page) {
  const csrf = await page.evaluate(async () => ((await (await fetch("/api/v1/auth/session")).json()) as { csrf_token: string }).csrf_token);
  const held = (await (await page.request.get("/api/v1/batches/runs/held")).json()) as Array<{ batch_id: string }>;
  for (const run of held) {
    const response = await page.request.post(`/api/v1/batches/${run.batch_id}/discard`, { headers: { "X-CSRF-Token": csrf } });
    expect(response.status(), await response.text()).toBe(204);
  }
}

test.beforeEach(async ({ signedInPage: page }) => {
  await discardHeldRuns(page);
});

test.afterEach(async ({ page }) => {
  await newTape(page);
});

test.describe("tape batches in parts (#277)", () => {
  test("51 labels print as two parts; the second starts after Continue", async ({ signedInPage: page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await cartOf(page, 51);
    await page.getByRole("button", { name: "Print 51 labels" }).click();
    await expect(stack(page).getByText("Part 1 of 2 is done. Check the tape, then continue.")).toBeVisible({ timeout: 30_000 });
    await stack(page).getByRole("button", { name: "Continue with part 2" }).click();
    await expect(done(page)).toBeVisible({ timeout: 30_000 });
  });

  test("the tape runs out inside a group: count, reprint from the first missing label, done", async ({ signedInPage: page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await tapeOutIn(page, 15);
    await cartOf(page, 25);
    await page.getByRole("button", { name: "Print 25 labels" }).click();
    await expect(stack(page).getByText(/Labels 11 to 20 may or may not have printed/)).toBeVisible({ timeout: 30_000 });
    await newTape(page);
    await stack(page).getByRole("combobox", { name: "First missing label" }).selectOption("16");
    await stack(page).getByRole("button", { name: "Reprint from label 16" }).click();
    await expect(done(page)).toBeVisible({ timeout: 30_000 });
  });

  test("a closed notification loses nothing: the jobs page keeps the stopped run and its actions", async ({ signedInPage: page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await tapeOutIn(page, 15);
    await cartOf(page, 25);
    await page.getByRole("button", { name: "Print 25 labels" }).click();
    await expect(stack(page).getByText(/Labels 11 to 20 may or may not have printed/)).toBeVisible({ timeout: 30_000 });
    await stack(page).getByRole("button", { name: "Dismiss notification" }).first().click();
    await newTape(page);
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Jobs" }).click();
    const held = page.getByRole("region", { name: "Tape prints that wait for you" });
    await expect(held.getByText(/Labels 11 to 20 may or may not have printed/)).toBeVisible();
    await held.getByRole("button", { name: "Discard" }).click();
    await expect(held).toHaveCount(0, { timeout: 15_000 });
  });

  test("screenshots: waiting for the next part and a stopped run", async ({ signedInPage: page }) => {
    test.skip(!SHOTS, "screenshots are an artifact, taken only with E2E_SHOTS_DIR");
    mkdirSync(SHOTS!, { recursive: true });
    test.setTimeout(160_000);
    for (const scheme of ["light", "dark"] as const) {
      await page.emulateMedia({ colorScheme: scheme });
      for (const [width, height] of [
        [1280, 800],
        [390, 844],
      ] as const) {
        await page.setViewportSize({ width, height });
        await cartOf(page, 51);
        await page.getByRole("button", { name: "Print 51 labels" }).click();
        await expect(stack(page).getByRole("button", { name: "Continue with part 2" })).toBeVisible({ timeout: 30_000 });
        await page.screenshot({ path: `${SHOTS}/task-22-waiting-${width}-${scheme}.png` });
        expect(await noSideScroll(page)).toBe(true);
        await stack(page).getByRole("button", { name: "Continue with part 2" }).click();
        await expect(done(page)).toBeVisible({ timeout: 30_000 });
        await stack(page).getByRole("button", { name: "Dismiss notification" }).first().click();

        await tapeOutIn(page, 15);
        await cartOf(page, 25);
        await page.getByRole("button", { name: "Print 25 labels" }).click();
        await expect(stack(page).getByRole("button", { name: "Reprint from label 11" })).toBeVisible({ timeout: 30_000 });
        await page.screenshot({ path: `${SHOTS}/task-22-stopped-${width}-${scheme}.png` });
        expect(await noSideScroll(page)).toBe(true);
        await stack(page).getByRole("button", { name: "Dismiss notification" }).first().click();
        await newTape(page);
      }
    }
  });
});
