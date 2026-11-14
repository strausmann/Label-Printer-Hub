// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import type { SheetPreview } from "../api";

type Hint = SheetPreview["reprint_hints"][number];

/** The earlier prints of one item on one sheet and one day. */
export interface ReprintRow {
  sheet: string;
  day: string;
  cells: number[];
  /** The latest `printed_at` of the row. */
  last: string;
}

/** Where one item was printed before: `count` earlier prints, newest row first. */
export interface ReprintGroup {
  itemIndex: number;
  count: number;
  rows: ReprintRow[];
}

/** `[2, 3, 4, 5, 6, 9]` → `"2–6, 9"`; each cell once, in order. */
export function cellRanges(cells: readonly number[]): string {
  const sorted = [...new Set(cells)].sort((a, b) => a - b);
  const parts: string[] = [];
  for (let i = 0; i < sorted.length; ) {
    let j = i;
    while (j + 1 < sorted.length && sorted[j + 1] === sorted[j]! + 1) j++;
    parts.push(i === j ? String(sorted[i]) : `${sorted[i]}–${sorted[j]}`);
    i = j + 1;
  }
  return parts.join(", ");
}

/**
 * The earlier prints grouped per item, one row per sheet and day (`dayOf` turns `printed_at` into the day in the
 * reader's time zone). A cell listed more than once (once per copy, by an older server) counts once.
 */
export function groupReprints(hints: readonly Hint[], dayOf: (printedAt: string) => string): ReprintGroup[] {
  const groups = new Map<number, Map<string, ReprintRow>>();
  const seen = new Set<string>();
  for (const h of hints) {
    const key = `${h.item_index}\u0000${h.sheet_code}\u0000${h.cell}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const day = dayOf(h.printed_at);
    const rows = groups.get(h.item_index) ?? new Map<string, ReprintRow>();
    groups.set(h.item_index, rows);
    const rowKey = `${h.sheet_code}\u0000${day}`;
    const row = rows.get(rowKey) ?? { sheet: h.sheet_code, day, cells: [], last: h.printed_at };
    row.cells.push(h.cell);
    if (h.printed_at > row.last) row.last = h.printed_at;
    rows.set(rowKey, row);
  }
  return [...groups].map(([itemIndex, rows]) => {
    const list = [...rows.values()].map((r) => ({ ...r, cells: [...r.cells].sort((a, b) => a - b) }));
    list.sort((a, b) => (a.last < b.last ? 1 : a.last > b.last ? -1 : 0));
    return { itemIndex, count: list.reduce((n, r) => n + r.cells.length, 0), rows: list };
  });
}
