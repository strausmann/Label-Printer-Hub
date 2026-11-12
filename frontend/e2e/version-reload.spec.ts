import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "./fixtures";

// Issue #288: a tab opened before an update reloads itself once when the hub reports another version.
// The hub under test runs the same build as the bundle, so the mismatch is mocked: every API response
// gets the header of a newer hub.

const SHOTS = process.env.E2E_SHOTS_DIR;
const NEWER = "99.0.0";

test.describe("new server version", () => {
  test("reloads once, then asks for a manual reload instead of looping", async ({ signedInPage: page }) => {
    let loads = 0;
    page.on("load", () => (loads += 1));
    await page.route("**/api/v1/**", async (route) => {
      const response = await route.fetch();
      await route.fulfill({ response, headers: { ...response.headers(), "x-hub-version": NEWER } });
    });

    // A client-side move: the page itself stays, only API calls go out and report the version.
    await page.getByRole("link", { name: "Printers", exact: true }).first().click();

    // One reload, and the reloaded (still old) bundle sees the same version: banner, no further reload.
    const banner = page.getByRole("status").filter({ hasText: "New version available" });
    await expect(banner).toBeVisible();
    expect(loads).toBe(1);
    await expect(page.getByRole("button", { name: "Reload" })).toBeVisible();
    // Still usable: the page content is there.
    await expect(page.getByRole("main")).toBeVisible();

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
