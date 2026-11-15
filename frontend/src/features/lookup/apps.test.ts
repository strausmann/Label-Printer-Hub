// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { describe, expect, it } from "vitest";
import { contentTypesFor, defaultContentTypeFor, LOOKUP_CONTENT_TYPES } from "./apps";

describe("content types per app (#346)", () => {
  it("Spoolman items offer the spool label first", () => {
    expect(contentTypesFor("spoolman")[0]).toBe("spool_swatch");
    expect(contentTypesFor("spoolman").slice(1)).toEqual(LOOKUP_CONTENT_TYPES);
  });

  // The start layout of a Spoolman item: the spool label only with swatch data on a sheet printer or a QL tape it is drawn for.
  it.each([
    ["sheet printer", { hasSwatch: true, backend: "ipp" }, "spool_swatch"],
    ["QL 62 mm", { hasSwatch: true, backend: "brother_ql", tapeMm: 62 }, "spool_swatch"],
    ["QL 29 mm (no spool label for that tape yet)", { hasSwatch: true, backend: "brother_ql", tapeMm: 29 }, "qr_two_lines"],
    ["QL, tape not known yet", { hasSwatch: true, backend: "brother_ql" }, "qr_two_lines"],
    ["P-touch 62 mm reading", { hasSwatch: true, backend: "ptouch", tapeMm: 62 }, "qr_two_lines"],
    ["P-touch", { hasSwatch: true, backend: "ptouch", tapeMm: 24 }, "qr_two_lines"],
    ["no printer", { hasSwatch: true }, "qr_two_lines"],
    ["no swatch data on a QL", { hasSwatch: false, backend: "brother_ql", tapeMm: 62 }, "qr_two_lines"],
    ["no swatch data on a sheet printer", { hasSwatch: false, backend: "ipp" }, "qr_two_lines"],
  ] as const)("Spoolman default on %s", (_, ctx, want) => {
    expect(defaultContentTypeFor("spoolman", ctx)).toBe(want);
  });

  it("without any context a Spoolman item starts on the default", () => {
    expect(defaultContentTypeFor("spoolman")).toBe("qr_two_lines");
  });

  it("other apps do not offer the spool label", () => {
    for (const app of ["snipeit", "grocy"] as const) {
      expect(contentTypesFor(app)).toEqual(LOOKUP_CONTENT_TYPES);
      expect(contentTypesFor(app)).not.toContain("spool_swatch");
      expect(defaultContentTypeFor(app)).toBe("qr_two_lines");
      expect(defaultContentTypeFor(app, { hasSwatch: true, backend: "ipp" })).toBe("qr_two_lines");
    }
  });
});
