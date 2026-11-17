// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import type { Page } from "@playwright/test";
import { expect } from "./fixtures";

/** The version a mocked newer hub reports; the hub under test runs the same build as the bundle. */
export const NEWER = "99.0.0";

/**
 * Makes every API answer of the page carry the version header of a newer hub, until the page sets
 * `sessionStorage["e2e-mismatch"] = "off"`. Done inside the page: with a service worker controlling it,
 * `page.route` does not see the requests.
 */
export async function reportNewerHub(page: Page) {
  await page.addInitScript((version) => {
    const realFetch = window.fetch.bind(window);
    window.fetch = async (...args: Parameters<typeof fetch>) => {
      const response = await realFetch(...args);
      const url = new URL(typeof args[0] === "string" ? args[0] : args[0] instanceof Request ? args[0].url : String(args[0]), location.href);
      if (!url.pathname.startsWith("/api/v1/") || sessionStorage.getItem("e2e-mismatch") === "off") return response;
      const headers = new Headers(response.headers);
      headers.set("x-hub-version", version);
      return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
    };
  }, NEWER);
  // The page was loaded before this script existed: load it again so the script is in place from the start.
  await page.reload();
  await expect(page.getByRole("navigation", { name: /^(Main|Tabs)$/ }).first()).toBeVisible();
}

/** The update toast (#354) and its Reload button. */
export const updateToast = (page: Page) => page.getByRole("region", { name: "New version" });
export const toastReload = (page: Page) => updateToast(page).getByRole("button", { name: "Reload" });
