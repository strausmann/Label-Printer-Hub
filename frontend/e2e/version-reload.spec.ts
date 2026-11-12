import { appendFileSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import type { Page } from "@playwright/test";
import { MAIN } from "./env";
import { expect, test } from "./fixtures";

// Issue #288: a tab opened before an update reloads itself once when the hub reports another version.
// The hub under test runs the same build as the bundle, so the mismatch is mocked: every API response
// gets the header of a newer hub.

const SHOTS = process.env.E2E_SHOTS_DIR;
const NEWER = "99.0.0";

/**
 * Makes every API answer of the page carry the version header of a newer hub, until the page sets
 * `sessionStorage["e2e-mismatch"] = "off"`. Done inside the page: with a service worker controlling it,
 * `page.route` does not see the requests.
 */
async function reportNewerHub(page: Page) {
  await page.addInitScript((version) => {
    const realFetch = window.fetch.bind(window);
    window.fetch = async (...args: Parameters<typeof fetch>) => {
      const response = await realFetch(...args);
      const url = new URL(typeof args[0] === "string" ? args[0] : args[0] instanceof Request ? args[0].url : String(args[0]), location.href);
      if (!url.pathname.startsWith("/api/") || sessionStorage.getItem("e2e-mismatch") === "off") return response;
      const headers = new Headers(response.headers);
      headers.set("x-hub-version", version);
      return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
    };
  }, NEWER);
  // The page was loaded before this script existed: load it again so the script is in place from the start.
  await page.reload();
  await expect(page.getByRole("navigation", { name: /^(Main|Tabs)$/ }).first()).toBeVisible();
}

test.describe("new server version", () => {
  test("shows the update notice and leaves the page alone", async ({ signedInPage: page }) => {
    let loads = 0;
    page.on("load", () => (loads += 1));
    await reportNewerHub(page);
    loads = 0;

    // A client-side move: the page itself stays, only API calls go out and report the version.
    await page.getByRole("link", { name: "Printers", exact: true }).first().click();

    const banner = page.getByRole("status").filter({ hasText: "New version available" });
    await expect(banner).toBeVisible();
    await expect(page.getByRole("button", { name: "Reload" })).toBeVisible();
    // No automatic reload, and the page is still usable.
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
          await page.screenshot({ path: resolve(SHOTS, `task-18b-${view.name}-${scheme}.png`) });
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
  test.afterAll(() => {
    writeFileSync(swFile, original);
  });

  test("one click on Reload ends on the new version, not on the old precached shell", async ({ signedInPage: page }) => {
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
    let loads = 0;
    page.on("load", () => (loads += 1));

    await page.getByRole("link", { name: "Printers", exact: true }).first().click();
    await expect(page.getByText("New version available")).toBeVisible();
    expect(loads).toBe(0);

    // The page that comes back runs the new bundle, so the hub reports its version again.
    await page.evaluate(() => sessionStorage.setItem("e2e-mismatch", "off"));
    // One click: the page asks for the new worker, applies it and reloads on the new files.
    await page.getByRole("button", { name: "Reload" }).click();
    await expect.poll(() => marker(), { timeout: 20_000 }).toBe("v2");
    await expect(page.getByRole("heading", { name: "Printers" }).first()).toBeVisible();
    expect(loads).toBe(1);
    await expect(page.getByText("New version available")).toHaveCount(0);
    expect(new URL(page.url()).origin).toBe(MAIN.url);
  });
});
