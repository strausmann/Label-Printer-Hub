// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import type { GeometryMm } from "../cellState";
import { pageSizeMm, remainingMargins } from "../cellState";

/** A rectangle on the back of the liner in mm (back-side coordinates, top = the sheet's top). */
export interface StripMm {
  x_mm: number;
  y_mm: number;
  w_mm: number;
  h_mm: number;
}

/** The code strip and where it goes, as the hub's `place_strip` does (R-350-3). */
export const CODE_STRIP = { w: 22, h: 62, gap: 2, origin: 10 } as const;

/** Where the code strip lands: centred in the first free strip that takes it, 2 mm below its top; (10, 10) mm without a design. `null` when none takes it. */
export function placeStrip(free: readonly StripMm[]): StripMm | null {
  if (free.length === 0) return { x_mm: CODE_STRIP.origin, y_mm: CODE_STRIP.origin, w_mm: CODE_STRIP.w, h_mm: CODE_STRIP.h };
  const fit = free.find((s) => s.w_mm >= CODE_STRIP.w && s.h_mm >= CODE_STRIP.gap + CODE_STRIP.h);
  if (!fit) return null;
  return { x_mm: fit.x_mm + (fit.w_mm - CODE_STRIP.w) / 2, y_mm: fit.y_mm + CODE_STRIP.gap, w_mm: CODE_STRIP.w, h_mm: CODE_STRIP.h };
}

/** The hub's assumption for a printer that does not report its margins (5 mm), its safety (1 mm) and the smallest band for the margin text (4 mm). */
const HW_MM = 5;
const SAFETY_MM = 1;
const MIN_BAND_MM = 4;

/** Whether a margin band of 4 mm fits this geometry with the assumed hardware margin: the rule `auto` resolves by without a printer. */
export function marginPossible(g: GeometryMm): boolean {
  const { right, bottom } = remainingMargins(g);
  const bands = [g.margin_top, bottom, right, g.margin_left].map((m) => m - HW_MM - SAFETY_MM);
  return Math.max(...bands) >= MIN_BAND_MM - 1e-9;
}

/** The deepest free band, for the reason text: the largest margin of the four sides, in mm. */
export function widestMargin(g: GeometryMm): number {
  const { right, bottom } = remainingMargins(g);
  return Math.max(g.margin_top, bottom, right, g.margin_left);
}

export { pageSizeMm };
