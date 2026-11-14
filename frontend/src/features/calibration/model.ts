// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import type { components } from "../../api/schema.gen";
import type { SheetTypeRead } from "../archive/api";
import type { FitRequest } from "./api";

type Reading = components["schemas"]["ReadingIn"];

/** A calibration page needs crossings: at least two columns and two rows. Anything else is not offered. */
export const usableTypes = (types: readonly SheetTypeRead[]): SheetTypeRead[] =>
  types.filter((t) => t.geometry.cols >= 2 && t.geometry.rows >= 2);

export interface Crossing {
  col_gap: number;
  row_gap: number;
}

/** The four outermost crossings; on a small grid the ones that coincide are dropped. */
export function suggestedCrossings(cols: number, rows: number): Crossing[] {
  const lastS = Math.max(cols - 1, 1);
  const lastZ = Math.max(rows - 1, 1);
  const all: Crossing[] = [
    { col_gap: 1, row_gap: 1 },
    { col_gap: lastS, row_gap: 1 },
    { col_gap: 1, row_gap: lastZ },
    { col_gap: lastS, row_gap: lastZ },
  ];
  return all.filter((c, i) => all.findIndex((o) => o.col_gap === c.col_gap && o.row_gap === c.row_gap) === i);
}

/** S counts the gaps between columns, Z the gaps between rows (the numbers printed on the page). */
export const crossingName = (colGap: number, rowGap: number): string => `S${colGap} · Z${rowGap}`;

/** A number as a person types it: decimal comma or point, an optional plus sign; null for anything else. */
export function parseNumber(value: string): number | null {
  const trimmed = value.trim().replace(",", ".");
  if (trimmed === "" || !/^[+-]?(\d+\.?\d*|\.\d+)$/.test(trimmed)) return null;
  const n = Number(trimmed);
  return Number.isFinite(n) ? n : null;
}

export interface ReadingRow extends Crossing {
  /** Local identity of the row (a list key), never sent. */
  id: number;
  across: string;
  down: string;
}

export const emptyReading = (id: number, at: Crossing = { col_gap: 1, row_gap: 1 }): ReadingRow => ({ id, ...at, across: "", down: "" });

export function completeReadings(rows: readonly ReadingRow[]): Reading[] {
  const out: Reading[] = [];
  for (const r of rows) {
    const across = parseNumber(r.across);
    const down = parseNumber(r.down);
    if (across !== null && down !== null) out.push({ col_gap: r.col_gap, row_gap: r.row_gap, across_mm: across, down_mm: down });
  }
  return out;
}

/** The server refuses fewer than three readings by validation; the button waits for three instead. */
export const MIN_READINGS = 3;
export const canFit = (rows: readonly ReadingRow[]): boolean => completeReadings(rows).length >= MIN_READINGS;

export const readingsRequest = (type: string, version: number, rows: readonly ReadingRow[]): FitRequest => ({
  type,
  version,
  readings: completeReadings(rows),
});
