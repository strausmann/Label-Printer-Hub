import { describe, expect, it } from "vitest";
import { sheetSummary } from "../../test-api";
import type { CartItem } from "../../lookup/cart";
import { countItems, expandItems, fittingFirst, freeOf, judgeSheet, MAX_ITEMS, placementFor, splitPlacements, type Fill } from "./plan";

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

describe("splitPlacements", () => {
  it("fills the free cells of the first sheet, then the rest goes onto a new sheet", () => {
    expect(splitPlacements(SHEET, "k", FILL, 3, { kind: "new" })).toEqual([
      { sheet: "L4736-0001", cells: "first_free", count: 3 },
      { new_sheet: { type: "k", id_placement: "margin" }, cells: "first_free" },
    ]);
  });

  it("or onto another sheet; the skipped cells stay skipped on the first", () => {
    expect(splitPlacements(SHEET, "k", { ...FILL, skipped: [4] }, 2, { kind: "sheet", code: "L4736-0004" })).toEqual([
      { sheet: "L4736-0001", cells: "first_free", skip: [4], count: 2 },
      { sheet: "L4736-0004", cells: "first_free" },
    ]);
  });

  it("a first sheet without a free cell is left out", () => {
    expect(splitPlacements(SHEET, "k", FILL, 0, { kind: "new" })).toEqual([{ new_sheet: { type: "k", id_placement: "margin" }, cells: "first_free" }]);
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
