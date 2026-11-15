// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { describe, expect, it } from "vitest";
import { docsUrl } from "./docsLink";

describe("docsUrl", () => {
  it.each([
    ["https://example.invalid/hub/tree/v1.5.1", "https://example.invalid/hub/blob/v1.5.1/docs/a.md#b"],
    ["https://example.invalid/hub/tree/0123456789abcdef0123456789abcdef01234567", "https://example.invalid/hub/blob/0123456789abcdef0123456789abcdef01234567/docs/a.md#b"],
    ["https://example.invalid/hub", "https://example.invalid/hub/blob/main/docs/a.md#b"],
  ])("%s", (source, want) => {
    expect(docsUrl(source, "docs/a.md#b")).toBe(want);
  });

  it("is null before the build info is known", () => {
    expect(docsUrl(null, "docs/a.md")).toBeNull();
    expect(docsUrl(undefined, "docs/a.md")).toBeNull();
  });
});
