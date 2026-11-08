import { ApiError } from "./client";

/*
 * Typed readers for the structured data of the error codes the sheet screens act on. Each one
 * returns null unless the error carries that code AND the expected fields, so a caller can chain
 * them without checking the code first and never reads a field of the wrong shape.
 */

type Detail = Record<string, unknown>;

function detailOf(error: unknown, code: string): Detail | null {
  return error instanceof ApiError && error.code === code ? error.errorDetail : null;
}

const isNumbers = (v: unknown): v is number[] => Array.isArray(v) && v.every((n) => typeof n === "number");
const isStrings = (v: unknown): v is string[] => Array.isArray(v) && v.every((s) => typeof s === "string");

export interface InsufficientCells {
  freeCells: number[];
  needed: number;
  shortfall: number;
}
/** `409 insufficient_cells`: the sheet cannot hold the items; the free cells let the cart split. */
export function insufficientCells(error: unknown): InsufficientCells | null {
  const d = detailOf(error, "insufficient_cells");
  if (!d || !isNumbers(d.free_cells) || typeof d.needed !== "number" || typeof d.shortfall !== "number") return null;
  return { freeCells: d.free_cells, needed: d.needed, shortfall: d.shortfall };
}

/** `409 plan_changed`: the server's current plan, to render again. */
export function planChanged(error: unknown): { plan: unknown } | null {
  const d = detailOf(error, "plan_changed");
  return d && "plan" in d ? { plan: d.plan } : null;
}

function reasonReader(code: string) {
  return (error: unknown): { reason: string } | null => {
    const d = detailOf(error, code);
    return d && typeof d.reason === "string" ? { reason: d.reason } : null;
  };
}
export const prefixTaken = reasonReader("prefix_taken");
export const readingsInsufficient = reasonReader("readings_insufficient");
export const typeInUse = reasonReader("type_in_use");

export interface CalibrationOutOfRange {
  field: string;
  min: number;
  max: number;
  reason: string;
}
/** `422 calibration_out_of_range`: which field and the range it must stay in. */
export function calibrationOutOfRange(error: unknown): CalibrationOutOfRange | null {
  const d = detailOf(error, "calibration_out_of_range");
  if (!d || typeof d.field !== "string" || typeof d.min !== "number" || typeof d.max !== "number" || typeof d.reason !== "string") {
    return null;
  }
  return { field: d.field, min: d.min, max: d.max, reason: d.reason };
}

function cellsReader(code: string) {
  return (error: unknown): { cells: number[] } | null => {
    const d = detailOf(error, code);
    return d && isNumbers(d.cells) ? { cells: d.cells } : null;
  };
}
export const cellsTaken = cellsReader("cells_taken");
export const cellsUnconfirmed = cellsReader("cells_unconfirmed");

/** `422 content_type_data_mismatch`: which item lacks which fields. */
export function contentTypeDataMismatch(error: unknown): { itemIndex: number; missingFields: string[] } | null {
  const d = detailOf(error, "content_type_data_mismatch");
  if (!d || typeof d.item_index !== "number" || !isStrings(d.missing_fields)) return null;
  return { itemIndex: d.item_index, missingFields: d.missing_fields };
}

/** `502 print_interrupted`: part of the batch is queued and keeps printing. */
export function printInterrupted(error: unknown): { batchId: string; jobIds: string[] } | null {
  const d = detailOf(error, "print_interrupted");
  if (!d || typeof d.batch_id !== "string" || !isStrings(d.job_ids)) return null;
  return { batchId: d.batch_id, jobIds: d.job_ids };
}

/** `500 sheet_id_job_failed`: the sheet exists, its ID page did not print. */
export function sheetIdJobFailed(error: unknown): { sheetCode: string } | null {
  const d = detailOf(error, "sheet_id_job_failed");
  return d && typeof d.sheet_code === "string" ? { sheetCode: d.sheet_code } : null;
}
