// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { msg } from "@lingui/core/macro";
import type { MessageDescriptor } from "@lingui/core";
import type { components } from "../../api/schema.gen";

export type GeometryMm = components["schemas"]["GeometryMm"];

export type GridCellState = "free" | "used" | "reserved" | "unconfirmed" | "new" | "skipped";

export interface GridCell {
  /** 1-based, row by row. */
  cell: number;
  state: GridCellState;
  purpose?: string;
  /** The sheet ID is printed on this cell. */
  isId?: boolean;
  /** The printed text was shortened. */
  truncated?: boolean;
  /** The purpose comes from an integration item. */
  mapped?: boolean;
  /** The cell reaches into the printer's unprintable margin. */
  hwMargin?: boolean;
}

export const CELL_STATES: readonly GridCellState[] = ["free", "used", "reserved", "unconfirmed", "new", "skipped"];

/** Page sizes the server knows (`geometry.py` PAGE_SIZES), used when `page_w`/`page_h` are absent. */
const PAGE_MM = { A4: { w: 210, h: 297 }, Letter: { w: 215.9, h: 279.4 } } as const;

/** Margins closer than this are not called asymmetric: the server's `_ASYMMETRY_HINT_HMM`. */
const ASYMMETRY_MM = 0.5;
/** Spec 17.6: nothing the finger has to hit is smaller than this. */
export const MIN_TAP_PX = 44;
/** Below this container width the select/skip modes switch to the zoomed tap view. */
export const TAP_VIEW_BELOW_PX = 640;
/** A fitted view never grows past this width, so a desktop page is not a poster. */
export const MAX_VIEW_PX = 760;

export function pageSizeMm(g: GeometryMm): { w: number; h: number } {
  const fallback = PAGE_MM[g.page_size] ?? PAGE_MM.A4;
  return { w: g.page_w ?? fallback.w, h: g.page_h ?? fallback.h };
}

export interface CellRect {
  x: number;
  y: number;
  w: number;
  h: number;
  row: number;
  col: number;
}

/** Position of cell `n` (1-based, row-major) on the page, in mm. */
export function cellRect(g: GeometryMm, n: number): CellRect {
  const row = Math.floor((n - 1) / g.cols);
  const col = (n - 1) % g.cols;
  return { x: g.margin_left + col * g.pitch_x, y: g.margin_top + row * g.pitch_y, w: g.label_w, h: g.label_h, row, col };
}

export function remainingMargins(g: GeometryMm): { right: number; bottom: number } {
  const page = pageSizeMm(g);
  return {
    right: page.w - (g.margin_left + (g.cols - 1) * g.pitch_x + g.label_w),
    bottom: page.h - (g.margin_top + (g.rows - 1) * g.pitch_y + g.label_h),
  };
}

/** Same rule as the server (`validate_geometry`), for a geometry that came without its hints. */
export function asymmetryHints(g: GeometryMm): string[] {
  const { right, bottom } = remainingMargins(g);
  const hints: string[] = [];
  if (Math.abs(right - g.margin_left) > ASYMMETRY_MM + 1e-9) hints.push("margins_asymmetric_x");
  if (Math.abs(bottom - g.margin_top) > ASYMMETRY_MM + 1e-9) hints.push("margins_asymmetric_y");
  return hints;
}

export type GridMode = "view" | "select" | "skip";

export interface GridLayout {
  /** The zoomed tap view for phones. */
  tap: boolean;
  /** Pixels per mm. */
  scale: number;
  width: number;
  height: number;
  pageW: number;
  pageH: number;
}

/**
 * Sizing of the grid, pure so that it can be unit-tested (jsdom has no layout engine).
 * `view` fits the container at the true aspect ratio; selecting below 640 px zooms until even the
 * smallest pitch box is 44 px, and the grid then scrolls inside its own container.
 */
export function gridLayout(g: GeometryMm, containerPx: number, mode: GridMode, zoom: 1 | 2 = 1): GridLayout {
  const { w: pageW, h: pageH } = pageSizeMm(g);
  const available = Math.max(containerPx, 1);
  const tap = mode !== "view" && available < TAP_VIEW_BELOW_PX;
  let scale = Math.min(available, MAX_VIEW_PX) / pageW;
  if (tap) scale = Math.max(scale, MIN_TAP_PX / Math.min(g.pitch_x, g.pitch_y));
  scale *= zoom;
  return { tap, scale, width: pageW * scale, height: pageH * scale, pageW, pageH };
}

export type Translate = (d: MessageDescriptor) => string;

/** Cell state words. A state and an action never share a message (lesson from #182): own context. */
const STATE_MESSAGES: Record<GridCellState, MessageDescriptor> = {
  free: msg({ message: "free", context: "sheet cell state" }),
  used: msg({ message: "used", context: "sheet cell state" }),
  reserved: msg({ message: "reserved", context: "sheet cell state" }),
  unconfirmed: msg({ message: "unconfirmed", context: "sheet cell state" }),
  new: msg({ message: "new", context: "sheet cell state" }),
  skipped: msg({ message: "skipped", context: "sheet cell state" }),
};

export function cellStateWord(state: GridCellState, t: Translate): string {
  return t(STATE_MESSAGES[state]);
}

/** "Cell 5, used, Grocy · flour 1 kg" — what a screen reader says for a cell. */
export function cellLabel(cell: GridCell, t: Translate): string {
  const state = cellStateWord(cell.state, t);
  const parts = [t(msg`Cell ${cell.cell}, ${state}`)];
  if (cell.isId) parts.push(t(msg`sheet ID`));
  if (cell.hwMargin) parts.push(t(msg`in the printer's unprintable margin`));
  if (cell.truncated) parts.push(t(msg`text shortened`));
  if (cell.purpose) parts.push(cell.purpose);
  return parts.join(", ");
}

/** Millimetres in the UI language: "9.85 mm" / "9,85 mm". At most two decimals. */
export function formatMm(value: number, locale: string): string {
  return `${new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(Math.round(value * 100) / 100)} mm`;
}
