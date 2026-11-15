// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { describe, expect, it } from "vitest";
import { sheetSummary } from "../../test-api";
import type { CartItem } from "../../lookup/cart";
import { cartLink, countItems, expandItems, fittingFirst, freeOf, judgeSheet, MAX_ITEMS, pickTray, placementFor, type Fill } from "./plan";

const line = (app: CartItem["app"], id: string, copies: number, content_type: CartItem["content_type"] = "qr_two_lines"): CartItem => ({
  app,
  id,
  name: `${app} ${id}`,
  content_type,
  copies,
});
const FILL: Fill = { mode: "first_free", chosen: [], skipped: [] };
const SHEET = { kind: "sheet", code: "L4736-0001" } as const;

describe("expandItems", () => {
  it("makes one sheet item per copy, with the cart line's layout and lookup", () => {
    const items = expandItems([line("grocy", "7", 2, "qr_one_line"), line("snipeit", "42", 1)]);
    expect(items).toEqual([
      { content_type: "qr_one_line", lookup: { app: "grocy", identifier: "7" } },
      { content_type: "qr_one_line", lookup: { app: "grocy", identifier: "7" } },
      { content_type: "qr_two_lines", lookup: { app: "snipeit", identifier: "42" } },
    ]);
    expect(countItems([line("grocy", "7", 2), line("snipeit", "42", 1)])).toBe(3);
  });

  it("the limit is the server's 500 items", () => {
    expect(MAX_ITEMS).toBe(500);
  });
});

describe("freeOf", () => {
  it("is total minus used, reserved and unconfirmed", () => {
    expect(freeOf({ total: 48, used: 17, reserved: 3, unconfirmed: 2 })).toBe(26);
    expect(freeOf({ total: 48, used: 48, reserved: 0, unconfirmed: 0 })).toBe(0);
  });
});

describe("placementFor", () => {
  it("an existing sheet takes the first free cells and may skip some", () => {
    expect(placementFor(SHEET, "k", FILL)).toEqual({ sheet: "L4736-0001", cells: "first_free" });
    expect(placementFor(SHEET, "k", { ...FILL, skipped: [2, 3] }, 3)).toEqual({ sheet: "L4736-0001", cells: "first_free", skip: [2, 3], count: 3 });
  });

  it("chosen cells are sent sorted and never together with skip", () => {
    expect(placementFor(SHEET, "k", { mode: "choose", chosen: [7, 5], skipped: [1] })).toEqual({ sheet: "L4736-0001", cells: [5, 7] });
  });

  it("a new sheet names its type and puts the ID in the margin, which takes no cell", () => {
    const placement = placementFor({ kind: "new" }, "avery-l4736rev", { mode: "choose", chosen: [4], skipped: [2] });
    expect(placement).toEqual({ new_sheet: { type: "avery-l4736rev", id_placement: "margin" }, cells: "first_free" });
    expect(placement).not.toHaveProperty("skip");
  });
});

describe("judgeSheet", () => {
  const sheet = (over = {}) => sheetSummary("L4736-0002", { type_key: "k", ...over });
  it.each([
    ["unknown when there is no such sheet", null, { kind: "unknown" }],
    ["discarded", sheet({ state: "discarded" }), { kind: "discarded" }],
    ["another type", sheet({ type_key: "other" }), { kind: "other_type", typeKey: "other" }],
    ["full, counting reserved and unconfirmed cells too", sheet({ total: 48, used: 40, reserved: 5, unconfirmed: 3, free: 3 }), { kind: "full" }],
    ["usable with room", sheet({ total: 48, used: 17, free: 31 }), { kind: "ok" }],
  ])("%s", (_name, input, verdict) => {
    expect(judgeSheet(input as never, "k")).toEqual(verdict);
  });

  it("a discarded sheet of another type is called discarded", () => {
    expect(judgeSheet(sheet({ state: "discarded", type_key: "other" }), "k")).toEqual({ kind: "discarded" });
  });
});

describe("fittingFirst", () => {
  const s = (code: string, free: number) => sheetSummary(code, { total: 48, used: 48 - free, free });
  it("puts the sheets that hold everything first, the tightest fit first, then the others by room", () => {
    const result = fittingFirst([s("A", 5), s("B", 30), s("C", 12), s("D", 3)], 9);
    expect(result.map((r) => [r.sheet.code, r.fits])).toEqual([
      ["C", true],
      ["B", true],
      ["A", false],
      ["D", false],
    ]);
  });
});

describe("cartLink", () => {
  it("carries an existing sheet and the tray", () => {
    expect(cartLink(SHEET, "tray-1", 2)).toEqual({ to: "/cart", search: { sheet: "L4736-0001", tray: "tray-1" } });
  });
  it("a new sheet carries no sheet", () => {
    expect(cartLink({ kind: "new" }, "tray-1", 2).search).toEqual({ tray: "tray-1" });
  });
  it("one tray carries no tray", () => {
    expect(cartLink(SHEET, "tray-1", 1).search).toEqual({ sheet: "L4736-0001" });
  });
  it("a target not known yet carries no sheet", () => {
    expect(cartLink(null, "tray-1", 2).search).toEqual({ tray: "tray-1" });
  });
  it("no tray chosen carries no tray", () => {
    expect(cartLink(SHEET, null, 3).search).toEqual({ sheet: "L4736-0001" });
  });
});

describe("pickTray", () => {
  const trays = [
    { key: "tray-1", is_default: false },
    { key: "tray-2", is_default: true },
    { key: "tray-3", is_default: false },
  ];
  it("the choice wins", () => {
    expect(pickTray(trays, "tray-3", "tray-1")?.key).toBe("tray-3");
  });
  it("then the address tray", () => {
    expect(pickTray(trays, null, "tray-1")?.key).toBe("tray-1");
  });
  it("an address tray the printer does not have falls back to the default", () => {
    expect(pickTray(trays, null, "tray-9")?.key).toBe("tray-2");
  });
  it("a choice the printer does not have falls through to the address tray", () => {
    expect(pickTray(trays, "gone", "tray-3")?.key).toBe("tray-3");
  });
  it("without a default the first", () => {
    expect(pickTray([{ key: "a", is_default: false }], null)?.key).toBe("a");
  });
  it("no trays gives null", () => {
    expect(pickTray([], "tray-1", "tray-2")).toBeNull();
  });
});
