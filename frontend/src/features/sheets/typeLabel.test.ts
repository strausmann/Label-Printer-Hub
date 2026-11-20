// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { describe, expect, it } from "vitest";
import { typeLabelWithKey, typePickerLabel, typeTitle } from "./typeLabel";

const BASE = { key: "avery-l4736rev", vendor: "Avery Zweckform" as string | null, product_codes: ["L4736REV-25", "L4736REV-10"], description: "48 labels, 45.7 x 21.2 mm" as string | null };

describe("typeTitle", () => {
  it("joins vendor, first product code and description", () => {
    expect(typeTitle(BASE)).toBe("Avery Zweckform L4736REV-25 · 48 labels, 45.7 x 21.2 mm");
  });

  it("uses the description alone without a vendor or without a product code", () => {
    expect(typeTitle({ ...BASE, vendor: null })).toBe("48 labels, 45.7 x 21.2 mm");
    expect(typeTitle({ ...BASE, product_codes: [] })).toBe("48 labels, 45.7 x 21.2 mm");
  });

  it("falls back to vendor and code without a description, treating a blank one as none", () => {
    expect(typeTitle({ ...BASE, description: null })).toBe("Avery Zweckform L4736REV-25");
    expect(typeTitle({ ...BASE, description: "  " })).toBe("Avery Zweckform L4736REV-25");
  });

  it("is the key for a user type that has nothing else", () => {
    expect(typeTitle({ key: "my-custom", vendor: null, product_codes: [], description: null })).toBe("my-custom");
  });

  it("treats an empty product code or a blank vendor like a missing one", () => {
    expect(typeTitle({ ...BASE, product_codes: [""], description: null })).toBe("avery-l4736rev");
    expect(typeTitle({ ...BASE, product_codes: [""] })).toBe("48 labels, 45.7 x 21.2 mm");
    expect(typeTitle({ ...BASE, vendor: "   ", description: null })).toBe("L4736REV-25");
    expect(typeTitle({ ...BASE, vendor: "   " })).toBe("48 labels, 45.7 x 21.2 mm");
    expect(typeLabelWithKey({ ...BASE, product_codes: [""], description: null })).toBe("avery-l4736rev");
  });

  it("keeps markup as plain text", () => {
    expect(typeTitle({ ...BASE, vendor: "<img src=x onerror=alert(1)>", description: "<b>x</b>" })).toBe(
      "<img src=x onerror=alert(1)> L4736REV-25 · <b>x</b>",
    );
  });
});

describe("pickers name a type like the archive does", () => {
  it("shows the title, the key in brackets and the size", () => {
    expect(typeLabelWithKey(BASE)).toBe("Avery Zweckform L4736REV-25 · 48 labels, 45.7 x 21.2 mm (avery-l4736rev)");
    expect(typePickerLabel({ ...BASE, geometry: { label_w: 45.7, label_h: 21.2 } }, "en", "archived")).toMatch(
      /^Avery Zweckform L4736REV-25 · 48 labels, 45\.7 x 21\.2 mm \(avery-l4736rev\) · 45\.7 × 21\.2 mm$/,
    );
  });

  it("does not repeat a key that is the whole title", () => {
    expect(typeLabelWithKey({ key: "my-custom", vendor: null, product_codes: [], description: null })).toBe("my-custom");
  });
});
