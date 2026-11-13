import { ApiError } from "./client";
import type { components } from "./schema.gen";

export type ExpectedPage = components["schemas"]["ExpectedPageModel"];

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
  /** The capacity left for items, a COUNT per placement of the request (after skip and the ID cell), not cell numbers. */
  capacity: number[];
  needed: number;
  shortfall: number;
}
/** `409 insufficient_cells`: the placements cannot hold the items; `free_cells` is one count per placement, which lets the cart split. */
export function insufficientCells(error: unknown): InsufficientCells | null {
  const d = detailOf(error, "insufficient_cells");
  if (!d || !isNumbers(d.free_cells) || typeof d.needed !== "number" || typeof d.shortfall !== "number") return null;
  return { capacity: d.free_cells, needed: d.needed, shortfall: d.shortfall };
}

const isExpectedPage = (v: unknown): v is ExpectedPage =>
  typeof v === "object" &&
  v !== null &&
  typeof (v as ExpectedPage).sheet === "string" &&
  isNumbers((v as ExpectedPage).cells) &&
  ((v as ExpectedPage).id_cell == null || typeof (v as ExpectedPage).id_cell === "number");

/** `409 plan_changed`: the server's current plan (one entry per page), to render again. */
export function planChanged(error: unknown): { plan: ExpectedPage[] } | null {
  const d = detailOf(error, "plan_changed");
  return d && Array.isArray(d.plan) && d.plan.every(isExpectedPage) ? { plan: d.plan } : null;
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

/** `422 invalid_import`: what the import document got wrong (the server's list, at most 20 entries). */
export function invalidImport(error: unknown): { errors: string[] } | null {
  const d = detailOf(error, "invalid_import");
  return d && isStrings(d.errors) ? { errors: d.errors } : null;
}

/** `422 invalid_geometry`: which field is wrong and the server's reason keyword. */
export function invalidGeometry(error: unknown): { field: string; reason: string } | null {
  const d = detailOf(error, "invalid_geometry");
  return d && typeof d.field === "string" && typeof d.reason === "string" ? { field: d.field, reason: d.reason } : null;
}

/** `422 label_too_long`: a text is longer than its limit. Same detail as `invalid_geometry`, its own code. */
export function labelTooLong(error: unknown): { field: string } | null {
  const d = detailOf(error, "label_too_long");
  return d && typeof d.field === "string" ? { field: d.field } : null;
}

/** `502 ipp_rejected`: the printer answered with an IPP status; its name, for example `server-error-busy`. */
export function ippRejected(error: unknown): { ippStatus: string } | null {
  const d = detailOf(error, "ipp_rejected");
  return d && typeof d.ipp_status === "string" && d.ipp_status !== "" ? { ippStatus: d.ipp_status } : null;
}

/** `409 tray_unknown`: the trays the printer reports (can be empty). */
export function trayUnknown(error: unknown): { trays: string[] } | null {
  const d = detailOf(error, "tray_unknown");
  return d && isStrings(d.trays) ? { trays: d.trays } : null;
}

/** The index of the item a failure belongs to (`content_type_data_mismatch`, `integration_*`), whatever the code. */
export function itemIndexOf(error: unknown): number | null {
  const d = error instanceof ApiError ? error.errorDetail : null;
  return d && typeof d.item_index === "number" ? d.item_index : null;
}

/** The jobs of the pages that were queued before a print failed (`print_interrupted`, or the merged detail of the failing page's own error); null when none were. */
export function queuedJobs(error: unknown): string[] | null {
  const d = error instanceof ApiError ? error.errorDetail : null;
  return d && isStrings(d.job_ids) && d.job_ids.length > 0 ? d.job_ids : null;
}
