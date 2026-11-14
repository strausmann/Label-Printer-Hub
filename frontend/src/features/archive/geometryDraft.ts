// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import type { GeometryMm } from "../sheets/cellState";
import { parseDecimal } from "./search";

/** The text of every geometry field while it is being edited. */
export interface GeometryDraft {
  pageSize: "A4" | "Letter";
  shape: "rectangle" | "round";
  cols: string;
  rows: string;
  labelW: string;
  labelH: string;
  pitchX: string;
  pitchY: string;
  marginTop: string;
  marginLeft: string;
  cornerRadius: string;
}

export const EMPTY_DRAFT: GeometryDraft = {
  pageSize: "A4",
  shape: "rectangle",
  cols: "",
  rows: "",
  labelW: "",
  labelH: "",
  pitchX: "",
  pitchY: "",
  marginTop: "",
  marginLeft: "",
  cornerRadius: "",
};

export function draftOf(g: GeometryMm): GeometryDraft {
  return {
    pageSize: g.page_size,
    shape: g.shape,
    cols: String(g.cols),
    rows: String(g.rows),
    labelW: String(g.label_w),
    labelH: String(g.label_h),
    pitchX: String(g.pitch_x),
    pitchY: String(g.pitch_y),
    marginTop: String(g.margin_top),
    marginLeft: String(g.margin_left),
    cornerRadius: g.corner_radius == null ? "" : String(g.corner_radius),
  };
}

export const MAX_MM = 1000;
export const MAX_CELLS_PER_AXIS = 400;

export type FieldName = "cols" | "rows" | "labelW" | "labelH" | "pitchX" | "pitchY" | "marginTop" | "marginLeft" | "cornerRadius";

/**
 * The geometry a draft describes, or the field that is wrong. The page size of the stored geometry
 * stays as it was (`page_w`, `page_h`) unless the paper size changed: the server derives them then.
 */
export function geometryOf(
  draft: GeometryDraft,
  previous?: GeometryMm,
): { geometry: GeometryMm } | { field: FieldName } {
  const whole = (value: string) => {
    const n = parseDecimal(value);
    return n !== null && Number.isInteger(n) && n >= 1 && n <= MAX_CELLS_PER_AXIS ? n : null;
  };
  const mm = (value: string, positive: boolean) => {
    const n = parseDecimal(value);
    return n !== null && n >= 0 && n <= MAX_MM && (!positive || n > 0) ? n : null;
  };
  const round = draft.shape === "round";
  const cols = whole(draft.cols);
  if (cols === null) return { field: "cols" };
  const rows = whole(draft.rows);
  if (rows === null) return { field: "rows" };
  const labelW = mm(draft.labelW, true);
  if (labelW === null) return { field: "labelW" };
  // A round label is as high as it is wide: the form asks for the diameter once.
  const labelH = round ? labelW : mm(draft.labelH, true);
  if (labelH === null) return { field: "labelH" };
  const pitchX = mm(draft.pitchX, true);
  if (pitchX === null) return { field: "pitchX" };
  const pitchY = mm(draft.pitchY, true);
  if (pitchY === null) return { field: "pitchY" };
  const marginTop = mm(draft.marginTop, false);
  if (marginTop === null) return { field: "marginTop" };
  const marginLeft = mm(draft.marginLeft, false);
  if (marginLeft === null) return { field: "marginLeft" };
  let cornerRadius: number | null = null;
  if (!round && draft.cornerRadius.trim() !== "") {
    cornerRadius = mm(draft.cornerRadius, false);
    if (cornerRadius === null) return { field: "cornerRadius" };
  }
  const keepPage = previous && previous.page_size === draft.pageSize;
  return {
    geometry: {
      page_size: draft.pageSize,
      page_w: keepPage ? (previous.page_w ?? null) : null,
      page_h: keepPage ? (previous.page_h ?? null) : null,
      shape: draft.shape,
      cols,
      rows,
      label_w: labelW,
      label_h: labelH,
      pitch_x: pitchX,
      pitch_y: pitchY,
      margin_top: marginTop,
      margin_left: marginLeft,
      corner_radius: cornerRadius,
    },
  };
}

/** Whether two geometries are the same measurements. The server refuses a new version that changes none of them (`unchanged`). */
export function sameGeometry(a: GeometryMm, b: GeometryMm): boolean {
  return (
    a.page_size === b.page_size &&
    a.shape === b.shape &&
    a.cols === b.cols &&
    a.rows === b.rows &&
    a.label_w === b.label_w &&
    a.label_h === b.label_h &&
    a.pitch_x === b.pitch_x &&
    a.pitch_y === b.pitch_y &&
    a.margin_top === b.margin_top &&
    a.margin_left === b.margin_left &&
    (a.corner_radius ?? null) === (b.corner_radius ?? null) &&
    (a.page_w ?? null) === (b.page_w ?? null) &&
    (a.page_h ?? null) === (b.page_h ?? null)
  );
}
