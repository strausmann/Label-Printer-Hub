import { describe, expect, it } from "vitest";
import { ApiError } from "./client";
import {
  calibrationOutOfRange,
  cellsTaken,
  cellsUnconfirmed,
  contentTypeDataMismatch,
  insufficientCells,
  invalidGeometry,
  invalidImport,
  ippRejected,
  itemIndexOf,
  planChanged,
  prefixTaken,
  printInterrupted,
  readingsInsufficient,
  trayUnknown,
  sheetIdJobFailed,
  typeInUse,
} from "./errorDetail";

const err = (code: string | null, detail: Record<string, unknown> | null) => new ApiError(409, code, "text", detail);

describe("typed error readers", () => {
  it("insufficientCells reads the capacity per placement, the need and the shortfall", () => {
    expect(insufficientCells(err("insufficient_cells", { free_cells: [3, 4], needed: 5, shortfall: 3 }))).toEqual({
      capacity: [3, 4],
      needed: 5,
      shortfall: 3,
    });
  });

  it("planChanged hands the new plan through", () => {
    const plan = [{ sheet: "L4736-0001", cells: [4, 5], id_cell: null }, { sheet: "new", cells: [1] }];
    expect(planChanged(err("plan_changed", { plan }))).toEqual({ plan });
    expect(planChanged(err("plan_changed", { plan: [{ sheet: 3, cells: [] }] }))).toBeNull();
    expect(planChanged(err("plan_changed", { plan: "x" }))).toBeNull();
  });

  it("prefixTaken, calibrationOutOfRange, readingsInsufficient, typeInUse", () => {
    expect(prefixTaken(err("prefix_taken", { reason: "L47 is used by L4736" }))).toEqual({ reason: "L47 is used by L4736" });
    expect(calibrationOutOfRange(err("calibration_out_of_range", { field: "offset_x_mm", min: -5, max: 5, reason: "too far" }))).toEqual({
      field: "offset_x_mm",
      min: -5,
      max: 5,
      reason: "too far",
    });
    expect(readingsInsufficient(err("readings_insufficient", { reason: "need 3" }))).toEqual({ reason: "need 3" });
    expect(typeInUse(err("type_in_use", { reason: "sheets exist" }))).toEqual({ reason: "sheets exist" });
  });

  it("cellsTaken and cellsUnconfirmed read the cells", () => {
    expect(cellsTaken(err("cells_taken", { cells: [1, 2] }))).toEqual({ cells: [1, 2] });
    expect(cellsUnconfirmed(err("cells_unconfirmed", { cells: [7] }))).toEqual({ cells: [7] });
  });

  it("contentTypeDataMismatch, printInterrupted, sheetIdJobFailed", () => {
    expect(contentTypeDataMismatch(err("content_type_data_mismatch", { item_index: 2, missing_fields: ["name"] }))).toEqual({
      itemIndex: 2,
      missingFields: ["name"],
    });
    expect(printInterrupted(new ApiError(502, "print_interrupted", "x", { batch_id: "b1", job_ids: ["j1", "j2"] }))).toEqual({
      batchId: "b1",
      jobIds: ["j1", "j2"],
    });
    expect(sheetIdJobFailed(new ApiError(500, "sheet_id_job_failed", "x", { sheet_code: "L4736-0001" }))).toEqual({
      sheetCode: "L4736-0001",
    });
  });

  it("returns null for another code, a missing detail or a malformed detail", () => {
    expect(insufficientCells(err("plan_changed", { free_cells: [1], needed: 1, shortfall: 0 }))).toBeNull();
    expect(insufficientCells(err("insufficient_cells", null))).toBeNull();
    expect(insufficientCells(err("insufficient_cells", { free_cells: "x", needed: 1, shortfall: 0 }))).toBeNull();
    expect(cellsTaken(err("cells_taken", { cells: [1, "2"] }))).toBeNull();
    expect(printInterrupted(new Error("plain"))).toBeNull();
    expect(printInterrupted(null)).toBeNull();
  });

  it("invalidImport and invalidGeometry read the server's lists and keywords", () => {
    expect(invalidImport(new ApiError(422, "invalid_import", "x", { errors: ["type.key", "version"] }))).toEqual({
      errors: ["type.key", "version"],
    });
    expect(invalidImport(new ApiError(422, "invalid_import", "x", { errors: [1] }))).toBeNull();
    expect(invalidImport(new ApiError(422, "invalid_import", "x", null))).toBeNull();
    expect(invalidGeometry(new ApiError(422, "invalid_geometry", "x", { field: "cols", reason: "too_large" }))).toEqual({
      field: "cols",
      reason: "too_large",
    });
    expect(invalidGeometry(new ApiError(422, "invalid_geometry", "x", { field: "cols" }))).toBeNull();
  });

  it("ippRejected reads the IPP status name", () => {
    expect(ippRejected(err("ipp_rejected", { ipp_status: "server-error-busy" }))).toEqual({ ippStatus: "server-error-busy" });
    expect(ippRejected(err("ipp_rejected", {}))).toBeNull();
    expect(ippRejected(err("ipp_unreachable", { ipp_status: "x" }))).toBeNull();
  });

  it("trayUnknown lists the trays the printer reports, itemIndexOf names the item an integration failed on", () => {
    expect(trayUnknown(err("tray_unknown", { trays: ["main", "bypass"] }))).toEqual({ trays: ["main", "bypass"] });
    expect(trayUnknown(err("tray_unknown", { trays: [] }))).toEqual({ trays: [] });
    expect(trayUnknown(err("tray_unknown", { trays: [1] }))).toBeNull();
    expect(trayUnknown(err("tray_unknown", null))).toBeNull();
    expect(trayUnknown(err("printer_disabled", { trays: [] }))).toBeNull();
    expect(itemIndexOf(err("integration_unreachable", { item_index: 3 }))).toBe(3);
    expect(itemIndexOf(err("integration_unreachable", { item_index: "3" }))).toBeNull();
    expect(itemIndexOf(err("integration_unreachable", null))).toBeNull();
    expect(itemIndexOf(new Error("plain"))).toBeNull();
  });
});
