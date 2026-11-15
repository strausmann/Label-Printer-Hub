// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// Behind an auth proxy (SSO) the manifest request must carry the session cookie, otherwise the
// proxy answers with a sign-in page and the browser refuses to install the app. A <link rel="manifest">
// is fetched without credentials unless it says crossorigin="use-credentials".
// This is a text check on index.html: it cannot see whether the browser really sends the cookie;
// no e2e check can: Playwright does not observe the cookie either (see e2e/shell.spec.ts).
describe("index.html manifest link", () => {
  it("manifest link is fetched with credentials", () => {
    const html = readFileSync(resolve(__dirname, "../index.html"), "utf8");
    const doc = new DOMParser().parseFromString(html, "text/html");
    const links = doc.querySelectorAll('link[rel="manifest"]');
    expect(links).toHaveLength(1);
    const link = links[0]!;
    expect(link.getAttribute("href")).toBe("/manifest.webmanifest");
    expect(link.getAttribute("crossorigin")).toBe("use-credentials");
  });
});
