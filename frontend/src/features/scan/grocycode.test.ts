// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { describe, expect, it } from "vitest";
import { GROCYCODE_SCAN, parseGrocycode } from "./grocycode";

describe("parseGrocycode", () => {
  it.each([
    ["grcy:p:13", { entity: "p", id: "13", extra: [] }],
    ["grcy:p:13:60bf8b5244b04", { entity: "p", id: "13", extra: ["60bf8b5244b04"] }],
    ["grcy:p:13:a:b", { entity: "p", id: "13", extra: ["a", "b"] }],
    ["grcy:b:4", { entity: "b", id: "4", extra: [] }],
    ["grcy:c:7", { entity: "c", id: "7", extra: [] }],
    ["  grcy:p:13 \n", { entity: "p", id: "13", extra: [] }],
  ])("reads %j", (text, want) => {
    expect(parseGrocycode(text)).toEqual(want);
  });

  it.each(["grcy:r:5", "grcy:x:1", "grcy:p:abc", "grocy:p:1", "grcy:p:", "grcy:p:13:", "GRCY:p:13", "", "https://hub.example.invalid/product/13"])(
    "does not read %j",
    (text) => {
      expect(parseGrocycode(text)).toBeNull();
    },
  );

  it("exports the pattern the scan matches", () => {
    expect(GROCYCODE_SCAN.test("grcy:b:4")).toBe(true);
    expect(GROCYCODE_SCAN.test("grcy:r:5")).toBe(false);
  });
});
