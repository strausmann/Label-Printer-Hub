import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { BOOTSTRAP } from "./env";
import { bootstrapKey, expect, mainKey, signInWith, test } from "./fixtures";

const SHOTS = process.env.E2E_SHOTS_DIR;

test.describe("shell", () => {
  test("desktop shows sidebar, 390px shows tab bar with Scan centred", async ({ signedInPage: page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    const sidebar = page.getByRole("navigation", { name: "Main" });
    await expect(sidebar).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Tabs" })).toBeHidden();
    for (const name of ["Overview", "Printers", "Jobs", "Sheets", "Sheet archive", "Calibration", "Snipe-IT", "Grocy", "Spoolman", "Settings"]) {
      await expect(sidebar.getByRole("link", { name, exact: true })).toBeVisible();
    }
    // Entries of modules that have not shipped stay hidden (features from /api/info): ASN and Kept.
    await expect(sidebar.getByRole("link", { name: "Paperless ASN" })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Scan" }).first()).toBeVisible();
    await expect(page.getByRole("combobox", { name: "Search" })).toBeVisible();
    if (SHOTS) {
      mkdirSync(SHOTS, { recursive: true });
      await page.screenshot({ path: resolve(SHOTS, "task-9-desktop.png") });
    }

    await page.setViewportSize({ width: 390, height: 844 });
    await expect(sidebar).toBeHidden();
    const tabs = page.getByRole("navigation", { name: "Tabs" });
    await expect(tabs).toBeVisible();
    await expect(tabs.getByRole("link")).toHaveText(["Overview", "Printers", "Scan", "Jobs", "Sheets"]);
    const scan = await tabs.getByRole("link", { name: "Scan" }).boundingBox();
    const bar = await tabs.boundingBox();
    expect(scan && bar).toBeTruthy();
    // Scan sits in the middle of the bar and is the largest target.
    expect(Math.abs(scan!.x + scan!.width / 2 - (bar!.x + bar!.width / 2))).toBeLessThan(2);
    const overview = await tabs.getByRole("link", { name: "Overview" }).boundingBox();
    expect(scan!.height).toBeGreaterThan(overview!.height - 1);
    expect(scan!.width).toBeGreaterThanOrEqual(56);
    // No horizontal scrolling on a phone.
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    if (SHOTS) await page.screenshot({ path: resolve(SHOTS, "task-9-phone.png") });
  });

  test("keyboard: Tab reaches every nav entry with visible focus", async ({ signedInPage: page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    const sidebar = page.getByRole("navigation", { name: "Main" });
    const names = await sidebar.getByRole("link").allInnerTexts();
    expect(names.map((n) => n.trim())).toEqual([
      "Overview",
      "Printers",
      "Jobs",
      "Sheets",
      "Sheet archive",
      "Calibration",
      "Snipe-IT",
      "Grocy",
      "Spoolman",
      "Settings",
    ]);

    await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
    const reached = new Set<string>();
    for (let i = 0; i < 40 && reached.size < names.length; i++) {
      await page.keyboard.press("Tab");
      const focus = await page.evaluate(() => {
        const el = document.activeElement as HTMLElement | null;
        if (!el || !el.closest('nav[aria-label="Main"]')) return null;
        const style = getComputedStyle(el);
        return { name: (el.textContent ?? "").trim(), outlineStyle: style.outlineStyle, outlineWidth: style.outlineWidth };
      });
      if (!focus) continue;
      // Focus must be visible: the 3px ring in the link colour (design rule), never removed.
      expect(focus.outlineStyle).not.toBe("none");
      expect(focus.outlineWidth).toBe("3px");
      reached.add(focus.name);
    }
    expect([...reached].sort()).toEqual([...names.map((n) => n.trim())].sort());
  });

  test("keyboard: the skip link moves focus to the content", async ({ signedInPage: page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
    await page.keyboard.press("Tab");
    const skip = page.getByRole("link", { name: "Skip to content" });
    await expect(skip).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.locator("#content")).toBeFocused();
  });

  test("theme choice sets data-theme and survives a reload", async ({ signedInPage: page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.getByRole("radio", { name: "Dark theme" }).check({ force: true });
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    expect(await page.evaluate(() => localStorage.getItem("lph.theme"))).toBe("dark");
    await page.getByRole("radio", { name: "System theme" }).check({ force: true });
    await expect(page.locator("html")).not.toHaveAttribute("data-theme", /.+/);
  });

  test("a client route that collides with a JSON route shows sign-in, then the page", async ({ page }) => {
    const job = "7f9c1c2e-1d0a-4c55-9a53-2f0f6c4f9a11";
    await page.goto(`/jobs/${job}`);
    await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
    await signInWith(page, mainKey());
    await expect(page).toHaveURL(new RegExp(`/jobs/${job}$`));
    await expect(page.getByRole("navigation", { name: /Main|Tabs/ }).first()).toBeVisible();
  });

  test("sign-in rejects a wrong key and signing out returns to sign-in", async ({ page }) => {
    await page.goto("/");
    await signInWith(page, "lh_pat_not-a-real-key-at-all");
    await expect(page.getByRole("alert")).toHaveText("That key was not accepted.");
    await expect(page.getByLabel("API key")).toHaveValue("");
    await signInWith(page, mainKey());
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.getByRole("button", { name: "Sign out" }).click();
    await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
    await expect(page).toHaveURL(/\/sign-in/);
  });
});

test.describe("bootstrap", () => {
  test.use({ baseURL: BOOTSTRAP.url });

  test("bootstrap flow creates first admin key", async ({ page }) => {
    await page.goto("/");
    await signInWith(page, bootstrapKey());
    await expect(page.getByRole("heading", { level: 1, name: "Create the first admin key" })).toBeVisible();
    // Until the first key exists, there is nothing else to do: no navigation.
    await expect(page.getByRole("navigation")).toHaveCount(0);
    await page.getByRole("button", { name: "Create admin key" }).click();

    const field = page.getByLabel("Your new admin key");
    await expect(field).toHaveValue(/^lh_pat_/);
    await expect(page.getByText("PRINTER_HUB_BOOTSTRAP_ADMIN_KEY")).toBeVisible();
    await expect(page.getByText("shown only once")).toBeVisible();
    const key = await field.inputValue();

    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page.getByRole("navigation", { name: /^(Main|Tabs)$/ }).first()).toBeVisible();
    // The new key is a real admin key: signing in with it works after a fresh session, and the
    // bootstrap key no longer does.
    await page.context().clearCookies();
    await page.goto("/");
    await signInWith(page, key);
    await expect(page.getByRole("navigation", { name: /^(Main|Tabs)$/ }).first()).toBeVisible();
    await page.context().clearCookies();
    await page.goto("/");
    await signInWith(page, bootstrapKey());
    await expect(page.getByRole("alert")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Create the first admin key" })).toHaveCount(0);
  });
});
