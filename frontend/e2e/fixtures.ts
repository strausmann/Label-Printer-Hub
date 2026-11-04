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

export const test = base.extend<{ signedInPage: Page }>({
  signedInPage: async ({ page }, use) => {
    await page.goto("/");
    await signInWith(page, mainKey());
    await expect(page.getByRole("navigation", { name: /^(Main|Tabs)$/ }).first()).toBeVisible();
    await use(page);
  },
});

export { expect };
