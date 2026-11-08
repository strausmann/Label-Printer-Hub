import { describe, expect, it } from "vitest";
import { GEOMETRY_L4736, SHEET_TYPE } from "../test-api";
import {
  canFit,
  completeReadings,
  crossingName,
  emptyReading,
  parseNumber,
  readingsRequest,
  suggestedCrossings,
  usableTypes,
  type ReadingRow,
} from "./model";

const type = (key: string, cols: number, rows: number) => ({ ...SHEET_TYPE, key, geometry: { ...GEOMETRY_L4736, cols, rows } });

describe("usableTypes", () => {
  it("offers only types with at least two columns and two rows", () => {
    const list = [type("grid", 4, 12), type("one-col", 1, 12), type("one-row", 4, 1), type("two", 2, 2), type("single", 1, 1)];
    expect(usableTypes(list).map((t) => t.key)).toEqual(["grid", "two"]);
  });
});

describe("suggestedCrossings", () => {
  it("are the four outermost crossings: S1/Z1, S(cols-1)/Z1, S1/Z(rows-1), S(cols-1)/Z(rows-1)", () => {
    expect(suggestedCrossings(4, 12)).toEqual([
      { col_gap: 1, row_gap: 1 },
      { col_gap: 3, row_gap: 1 },
      { col_gap: 1, row_gap: 11 },
      { col_gap: 3, row_gap: 11 },
    ]);
  });

  it("drops the crossings that coincide on a small grid", () => {
    expect(suggestedCrossings(2, 5)).toEqual([
      { col_gap: 1, row_gap: 1 },
      { col_gap: 1, row_gap: 4 },
    ]);
    expect(suggestedCrossings(2, 2)).toEqual([{ col_gap: 1, row_gap: 1 }]);
  });
});

describe("crossingName", () => {
  it("is S for the column gap and Z for the row gap", () => {
    expect(crossingName(2, 6)).toBe("S2 · Z6");
  });
});

describe("parseNumber", () => {
  it("accepts a decimal comma, a plus sign and spaces", () => {
    expect(parseNumber(" +0,8 ")).toBe(0.8);
    expect(parseNumber("-0.4")).toBe(-0.4);
  });
  it("is null for empty, text and non-finite input", () => {
    expect(parseNumber("")).toBeNull();
    expect(parseNumber("abc")).toBeNull();
    expect(parseNumber("1e999")).toBeNull();
    expect(parseNumber("0,8 mm")).toBeNull();
  });
});

const row = (col_gap: number, row_gap: number, across: string, down: string): ReadingRow => ({ ...emptyReading(1), col_gap, row_gap, across, down });

describe("readings", () => {
  const rows = [row(1, 1, "0,2", "-0,1"), row(3, 1, "0.4", "0"), row(1, 11, "", ""), row(3, 11, "0,6", "x")];

  it("only complete rows (both numbers valid) count", () => {
    expect(completeReadings(rows)).toHaveLength(2);
  });

  it("Fit needs three complete readings", () => {
    expect(canFit(rows)).toBe(false);
    expect(canFit([...rows, row(3, 11, "0,6", "0,3")])).toBe(true);
  });

  it("builds the request with the type, its version and the readings in mm", () => {
    const request = readingsRequest("L4736REV", 2, [row(1, 1, "0,2", "-0,1"), row(3, 1, "0.4", "0"), row(1, 11, "1", "1")]);
    expect(request).toEqual({
      type: "L4736REV",
      version: 2,
      readings: [
        { col_gap: 1, row_gap: 1, across_mm: 0.2, down_mm: -0.1 },
        { col_gap: 3, row_gap: 1, across_mm: 0.4, down_mm: 0 },
        { col_gap: 1, row_gap: 11, across_mm: 1, down_mm: 1 },
      ],
    });
  });
});
