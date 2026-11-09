import { readFileSync } from "node:fs";
import { test as base, expect, type Page } from "@playwright/test";
import { BOOTSTRAP, MAIN } from "./env";

/** The key the test hub wrote for us: plaintext, never logged. */
export const mainKey = () => readFileSync(MAIN.keyFile, "utf8").trim();
export const bootstrapKey = () => readFileSync(BOOTSTRAP.keyFile, "utf8").trim();

/** Fills the sign-in screen and waits until the shell is there. */
export async function signInWith(page: Page, key: string): Promise<void> {
  await page.getByLabel("API key").fill(key);
  await page.getByRole("button", { name: "Sign in" }).click();
}

/** What `GET /__e2e/page-printer` answers: the fake's address and what it currently reports. */
export type PagePrinterControl = { uri: string; state: Record<string, unknown> };

/** The state the fake page printer can be switched to (test-only control path, loopback only). */
export type PagePrinterState = {
  printer_state?: number;
  reasons?: string[];
  markers?: { name: string; color?: string; level?: number; low_level?: number; type?: string }[];
  accepting_jobs?: boolean;
  job_script?: number[];
  /** Hardware margins the printer reports, in hundredths of a millimetre. */
  margins_hmm?: number;
  /** Polls that report "stopping" after a Cancel-Job. */
  cancel_steps?: number;
};

/** Switches the fake page printer; the hub notices on its next status probe (1 s in the test hub). */
export async function setPagePrinter(page: Page, state: PagePrinterState): Promise<void> {
  const response = await page.request.post(`${MAIN.url}/__e2e/page-printer/state`, { data: state });
  expect(response.ok(), await response.text()).toBe(true);
}

/** Puts the fake page printer back to idle and ready. Every spec that switches it calls this in `afterEach`. */
export async function resetPagePrinter(page: Page): Promise<void> {
  const response = await page.request.post(`${MAIN.url}/__e2e/page-printer/reset`);
  expect(response.ok(), await response.text()).toBe(true);
}

/** The fake's `ipp://` address and its current state. */
export async function pagePrinterControl(page: Page): Promise<PagePrinterControl> {
  const response = await page.request.get(`${MAIN.url}/__e2e/page-printer`);
  expect(response.headers()["content-type"]).toContain("application/json");
  return (await response.json()) as PagePrinterControl;
}

export const test = base.extend<{ signedInPage: Page }>({
  signedInPage: async ({ page }, use) => {
    await page.goto("/");
    await signInWith(page, mainKey());
    await expect(page.getByRole("navigation", { name: /^(Main|Tabs)$/ }).first()).toBeVisible();
    await use(page);
    // A route handler that is still inside `route.fetch()` when the test ends throws "Test ended"
    // into whatever test is reported next. Drop every route and let in-flight handlers fail quietly.
    await page.unrouteAll({ behavior: "ignoreErrors" });
  },
});

export { expect };
