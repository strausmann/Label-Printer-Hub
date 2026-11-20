// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { describe, expect, it } from "vitest";
import { httpUrl } from "./search";

describe("httpUrl", () => {
  it("httpUrl returns the normalised href", () => {
    expect(httpUrl("HTTPS://Example.invalid/a b")).toBe("https://example.invalid/a%20b");
  });
  it.each(["javascript:alert(1)", "data:text/html,x", "", null, undefined, "not a url"])("refuses %s", (value) => {
    expect(httpUrl(value)).toBeNull();
  });
});
