// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { describe, expect, it } from "vitest";
import { contentTypesFor, defaultContentTypeFor, LOOKUP_CONTENT_TYPES } from "./apps";

describe("content types per app (#346)", () => {
  it("Spoolman items offer the spool label first and as default", () => {
    expect(contentTypesFor("spoolman")[0]).toBe("spool_swatch");
    expect(contentTypesFor("spoolman").slice(1)).toEqual(LOOKUP_CONTENT_TYPES);
    expect(defaultContentTypeFor("spoolman")).toBe("spool_swatch");
  });

  it("other apps do not offer the spool label", () => {
    for (const app of ["snipeit", "grocy"] as const) {
      expect(contentTypesFor(app)).toEqual(LOOKUP_CONTENT_TYPES);
      expect(contentTypesFor(app)).not.toContain("spool_swatch");
      expect(defaultContentTypeFor(app)).toBe("qr_two_lines");
    }
  });
});
