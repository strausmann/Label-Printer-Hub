// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { describe, expect, it } from "vitest";
import { plannedCellsText } from "./plannedCells";

describe("plannedCellsText", () => {
  it("turns a contiguous run into a range with an en dash", () => {
    expect(plannedCellsText([{ sheet: "L4736-0001", cells: [2, 3, 4, 5, 6] }])).toEqual([{ cells: "2–6", sheet: "L4736-0001" }]);
  });

  it("lists single cells and separate runs", () => {
    expect(plannedCellsText([{ sheet: "A", cells: [2, 4] }])).toEqual([{ cells: "2, 4", sheet: "A" }]);
    expect(plannedCellsText([{ sheet: "A", cells: [1, 2, 3, 7, 9, 10] }])).toEqual([{ cells: "1–3, 7, 9–10", sheet: "A" }]);
  });

  it("a pair of neighbours is a range, a single cell is just the number", () => {
    expect(plannedCellsText([{ sheet: "A", cells: [5] }])).toEqual([{ cells: "5", sheet: "A" }]);
    expect(plannedCellsText([{ sheet: "A", cells: [5, 6] }])).toEqual([{ cells: "5–6", sheet: "A" }]);
  });

  it("gives one entry per sheet, in order, and sorts unordered cells", () => {
    expect(
      plannedCellsText([
        { sheet: "L4736-0001", cells: [47, 48] },
        { sheet: "L4736-0002", cells: [3, 1, 2] },
      ]),
    ).toEqual([
      { cells: "47–48", sheet: "L4736-0001" },
      { cells: "1–3", sheet: "L4736-0002" },
    ]);
  });

  it("leaves out a sheet that takes no cell", () => {
    expect(plannedCellsText([{ sheet: "A", cells: [] }, { sheet: "B", cells: [4] }])).toEqual([{ cells: "4", sheet: "B" }]);
  });
});
