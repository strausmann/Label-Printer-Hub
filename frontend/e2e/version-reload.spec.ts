// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { appendFileSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import type { Page } from "@playwright/test";
import { MAIN } from "./env";
import { expect, test } from "./fixtures";
import { NEWER, reportNewerHub, toastReload, updateToast } from "./newerHub";

// Issue #288: a tab opened before an update shows the update notice when the hub reports another version; one click on Reload lands on the new version.
// Issue #354: the notice is a toast, a box in the sidebar and an entry in the notification centre.
// The hub under test runs the same build as the bundle, so the mismatch is mocked: every API response
// gets the header of a newer hub.

const SHOTS = process.env.E2E_SHOTS_DIR;

test.describe("new server version", () => {
  test("shows the update notice and leaves the page alone", async ({ signedInPage: page }) => {
    let loads = 0;
    page.on("load", () => (loads += 1));
    await reportNewerHub(page);
    loads = 0;

    // A client-side move: the page itself stays, only API calls go out and report the version.
    await page.getByRole("link", { name: "Printers", exact: true }).first().click();

    const banner = updateToast(page);
    await expect(banner.getByRole("status")).toContainText("New version available");
    await expect(banner).toContainText(`Version ${NEWER}`);
    await expect(toastReload(page)).toBeVisible();
    // The box in the sidebar and the entry in the notification centre say the same.
    const sidebar = page.getByRole("complementary");
    await expect(sidebar.getByRole("button", { name: "Reload new version" })).toBeVisible();
    await expect(sidebar).toContainText(`${NEWER} ready`);
    await page.getByRole("button", { name: /^Notifications/ }).click();
    const panel = page.getByRole("dialog");
    await expect(panel.getByText(`New version ${NEWER} available`)).toBeVisible();
    await expect(panel.getByRole("button", { name: "Reload new version" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(panel).toHaveCount(0);
    // Nothing in the page content any more, no automatic reload, and the page is still usable.
    await expect(page.getByRole("main").getByText("New version available")).toHaveCount(0);
    await expect(page.getByRole("main")).toBeVisible();
    expect(loads).toBe(0);

    if (SHOTS) {
      mkdirSync(SHOTS, { recursive: true });
      const views = [
        { name: "desktop", width: 1280, height: 800 },
        { name: "phone", width: 390, height: 844 },
        { name: "short-desktop", width: 1280, height: 500 },
        { name: "short-phone", width: 390, height: 400 },
      ];
      for (const scheme of ["light", "dark"] as const) {
        await page.emulateMedia({ colorScheme: scheme });
        for (const view of views) {
          await page.setViewportSize({ width: view.width, height: view.height });
          await expect(banner).toBeVisible();
          await page.screenshot({ path: resolve(SHOTS, `task-15m-${view.name}-${scheme}.png`) });
        }
      }
      await page.emulateMedia({ colorScheme: "light" });
    }
  });

  test("does not reload when the hub reports the version of the bundle", async ({ signedInPage: page }) => {
    let loads = 0;
    page.on("load", () => (loads += 1));
    const answered = page.waitForResponse((r) => r.url().includes("/api/v1/printers") && r.ok());
    await page.getByRole("link", { name: "Printers", exact: true }).first().click();
    const response = await answered;
    // The real hub names its version, and it is the one the bundle was built for.
    expect(response.headers()["x-hub-version"]).toBeTruthy();
    await expect(page.getByRole("heading", { name: "Printers" }).first()).toBeVisible();
    expect(loads).toBe(0);
    await expect(page.getByText("New version available")).toHaveCount(0);
  });
});

// The real service worker of the production build: the hub serves `dist/`, so a changed `dist/sw.js` is a new
// version of the worker for the browser. The mismatch is the mocked header; the worker that takes over answers
// `/__sw-marker`, which the old one does not.
test.describe("new server version with a real service worker", () => {
  const swFile = resolve(import.meta.dirname, "..", "dist", "sw.js");
  let original = "";
  test.beforeAll(() => {
    original = readFileSync(swFile, "utf8");
  });
  // Each case starts from the shipped worker: a worker left changed by the previous case would already answer "v2".
  test.beforeEach(() => {
    writeFileSync(swFile, original);
  });
  test.afterAll(() => {
    writeFileSync(swFile, original);
  });

  /** Waits for the old worker, ships a new one and reports a newer hub; returns the page's marker reader. */
  async function newVersionWaiting(page: Page) {
    // The first page load registered the worker; wait until it controls the page.
    await page.evaluate(async () => {
      await navigator.serviceWorker.ready;
    });
    await expect.poll(() => page.evaluate(() => navigator.serviceWorker.controller !== null)).toBe(true);
    // The hub answers unknown paths with the app shell, so only the worker's own answer says "v2".
    // "navigating" while the page is between two loads.
    const marker = () => page.evaluate(async () => (await fetch("/__sw-marker")).text()).catch(() => "navigating");
    await expect.poll(marker).not.toBe("navigating");
    expect(await marker()).not.toBe("v2");

    // The hub now serves a new worker (a new version of the app).
    appendFileSync(
      swFile,
      '\nself.addEventListener("fetch", (e) => { if (new URL(e.request.url).pathname === "/__sw-marker") e.respondWith(new Response("v2")); });\n',
    );

    await reportNewerHub(page);
    return marker;
  }

  test("Later hides the toast and the sidebar still reloads", async ({ signedInPage: page }) => {
    const marker = await newVersionWaiting(page);
    let loads = 0;
    page.on("load", () => (loads += 1));
    await page.getByRole("link", { name: "Printers", exact: true }).first().click();
    await expect(updateToast(page)).toBeVisible();
    await updateToast(page).getByRole("button", { name: "Later" }).click();
    await expect(updateToast(page)).toHaveCount(0);
    expect(loads).toBe(0);

    await page.evaluate(() => sessionStorage.setItem("e2e-mismatch", "off"));
    await page.getByRole("complementary").getByRole("button", { name: "Reload new version" }).click();
    await expect.poll(() => marker(), { timeout: 20_000 }).toBe("v2");
    await expect(page.getByRole("heading", { name: "Printers" }).first()).toBeVisible();
    expect(loads).toBe(1);
    await expect(page.getByRole("complementary").getByRole("button", { name: "Reload new version" })).toHaveCount(0);
    expect(new URL(page.url()).origin).toBe(MAIN.url);
  });

  test("one click on Reload ends on the new version, not on the old precached shell", async ({ signedInPage: page }) => {
    const marker = await newVersionWaiting(page);
    let loads = 0;
    page.on("load", () => (loads += 1));

    await page.getByRole("link", { name: "Printers", exact: true }).first().click();
    await expect(page.getByText("New version available")).toBeVisible();
    expect(loads).toBe(0);

    // The page that comes back runs the new bundle, so the hub reports its version again.
    await page.evaluate(() => sessionStorage.setItem("e2e-mismatch", "off"));
    // One click: the page asks for the new worker, applies it and reloads on the new files.
    await toastReload(page).click();
    await expect.poll(() => marker(), { timeout: 20_000 }).toBe("v2");
    await expect(page.getByRole("heading", { name: "Printers" }).first()).toBeVisible();
    expect(loads).toBe(1);
    await expect(page.getByText("New version available")).toHaveCount(0);
    expect(new URL(page.url()).origin).toBe(MAIN.url);
  });
});
