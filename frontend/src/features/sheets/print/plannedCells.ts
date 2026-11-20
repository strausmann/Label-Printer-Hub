// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * The cells a print plans, as words: contiguous runs become ranges (`[2,3,4,5,6]` → `"2–6"`), single cells stay
 * numbers (`[2,4]` → `"2, 4"`). One entry per sheet that takes at least one cell, in the order of the pages.
 */
export function plannedCellsText(pages: readonly { sheet: string; cells: readonly number[] }[]): { cells: string; sheet: string }[] {
  const out: { cells: string; sheet: string }[] = [];
  for (const page of pages) {
    const sorted = [...page.cells].sort((a, b) => a - b);
    const runs: string[] = [];
    for (let i = 0; i < sorted.length; ) {
      let j = i;
      while (j + 1 < sorted.length && sorted[j + 1] === sorted[j]! + 1) j++;
      runs.push(j > i ? `${sorted[i]}–${sorted[j]}` : String(sorted[i]));
      i = j + 1;
    }
    if (runs.length > 0) out.push({ cells: runs.join(", "), sheet: page.sheet });
  }
  return out;
}
