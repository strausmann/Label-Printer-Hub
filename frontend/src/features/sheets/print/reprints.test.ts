// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { describe, expect, it } from "vitest";
import { cellRanges, groupReprints } from "./reprints";

const day = (iso: string) => iso.slice(0, 10);

describe("cellRanges", () => {
  it("joins runs of neighbouring cells into ranges", () => {
    expect(cellRanges([6, 2, 3, 4, 5])).toBe("2–6");
    expect(cellRanges([2, 4, 5, 9])).toBe("2, 4–5, 9");
    expect(cellRanges([5])).toBe("5");
  });

  it("counts a cell once", () => {
    expect(cellRanges([3, 3, 4])).toBe("3–4");
  });
});

describe("groupReprints", () => {
  const hint = (item_index: number, sheet_code: string, cell: number, printed_at = "2026-11-14T08:00:00Z") => ({ item_index, sheet_code, cell, printed_at });

  it("groups the earlier prints per item, with one row per sheet and day", () => {
    const groups = groupReprints(
      [hint(0, "L4736-0001", 2), hint(0, "L4736-0001", 3), hint(0, "L4736-0002", 7, "2026-11-01T08:00:00Z"), hint(1, "L4736-0001", 9)],
      day,
    );
    expect(groups).toEqual([
      { itemIndex: 0, count: 3, rows: [
        { sheet: "L4736-0001", day: "2026-11-14", cells: [2, 3], last: "2026-11-14T08:00:00Z" },
        { sheet: "L4736-0002", day: "2026-11-01", cells: [7], last: "2026-11-01T08:00:00Z" },
      ] },
      { itemIndex: 1, count: 1, rows: [{ sheet: "L4736-0001", day: "2026-11-14", cells: [9], last: "2026-11-14T08:00:00Z" }] },
    ]);
  });

  it("counts each earlier print once, even when it is listed for every copy", () => {
    const five = [2, 3, 4, 5, 6].map((c) => hint(0, "L4736-0001", c));
    const repeated = Array.from({ length: 10 }, () => five).flat();
    const [group] = groupReprints(repeated, day);
    expect(group!.count).toBe(5);
    expect(group!.rows).toHaveLength(1);
    expect(group!.rows[0]!.cells).toEqual([2, 3, 4, 5, 6]);
  });
});
