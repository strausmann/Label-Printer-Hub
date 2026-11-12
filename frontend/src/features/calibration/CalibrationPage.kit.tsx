import { act, fireEvent, screen } from "@testing-library/react";
import { afterEach, vi } from "vitest";
import { renderApp, SIGNED_IN } from "../../test-utils";
import { GEOMETRY_L4736, mockApi, PAGE_CAPABILITIES, PAGE_PRINTER, pageStatus, PRINTER_A, SHEET_TYPE, status, type Call } from "../test-api";

// What the CalibrationPage test files share. The page is a whole app render in jsdom (react-aria selects, a
// schematic), 60-250 ms per step, so its tests live in several files that vitest runs side by side, split by concern.

/** Registers the reset every file here needs: no stubbed globals left behind. Call it at the top of the file. */
export function resetBetweenTests(): void {
  afterEach(() => vi.unstubAllGlobals());
}

export const P = PAGE_PRINTER.id;
export const BASE = `/api/v1/printers/${P}/calibration`;
export const JOB = "dddddddd-0000-4000-8000-000000000001";
export const RETRY = "dddddddd-0000-4000-8000-000000000002";
export const READ_SESSION = { ...SIGNED_IN, scope: "read" as const };
export const PRINT_SESSION = { ...SIGNED_IN, scope: "print" as const };

export const stored = {
  tray: "main",
  offset_x_mm: 0.4,
  offset_y_mm: -0.2,
  scale_x: 1.001,
  scale_y: 1,
  rotation_deg: 0.05,
  method: "manual",
  updated_at: "2026-11-04T10:00:00Z",
  measured_on: { type_key: "L4736REV", version: 1 },
};
export const none = { tray: "bypass", offset_x_mm: null, offset_y_mm: null, scale_x: null, scale_y: null, rotation_deg: null, method: null, updated_at: null };
export const oneColumn = { ...SHEET_TYPE, key: "ONECOL", prefix: "O1", product_codes: [], vendor: "One", geometry: { ...GEOMETRY_L4736, cols: 1 } };
export const secondPrinter = { ...PAGE_PRINTER, id: "44444444-4444-4444-8444-444444444444", name: "Second laser", slug: "second" };
export const typeB = { ...SHEET_TYPE, key: "OTHERTYPE", prefix: "OT", vendor: "Other", product_codes: ["OT-1"], current_version: 3 };
export const twoColumns = { ...SHEET_TYPE, key: "TWOCOL", prefix: "T2", vendor: "Two", product_codes: ["T2-1"], geometry: { ...GEOMETRY_L4736, cols: 2 } };
export const disabledPrinter = { ...PAGE_PRINTER, id: "55555555-5555-4555-8555-555555555555", name: "Switched off laser", enabled: false };

export function routes(extra: Record<string, unknown> = {}) {
  return {
    "GET /api/v1/printers": [PAGE_PRINTER, secondPrinter, PRINTER_A, disabledPrinter],
    [`GET /api/v1/printers/${P}/status`]: pageStatus(P),
    [`GET /api/v1/printers/${secondPrinter.id}/status`]: pageStatus(secondPrinter.id),
    [`GET /api/v1/printers/${PRINTER_A.id}/status`]: status(PRINTER_A.id),
    [`GET /api/v1/printers/${P}/capabilities`]: PAGE_CAPABILITIES,
    [`GET /api/v1/printers/${secondPrinter.id}/capabilities`]: PAGE_CAPABILITIES,
    [`GET ${BASE}`]: [stored, none],
    [`GET /api/v1/printers/${secondPrinter.id}/calibration`]: [{ ...none, tray: "main" }],
    "GET /api/v1/sheet-types": [SHEET_TYPE, oneColumn],
    ...extra,
  };
}

export async function open(extra: Record<string, unknown> = {}, session = SIGNED_IN, path = `/calibration?printer=${P}&tray=main`) {
  const api = mockApi(routes(extra));
  const app = await renderApp({ path, session });
  await screen.findByRole("heading", { level: 1, name: "Calibration" });
  return { ...api, ...app };
}

export const only = (calls: Call[], method: string, suffix = "") => calls.filter((c) => c.method === method && c.path.endsWith(suffix));
export const body = (call: Call | undefined) => JSON.parse(call?.body ?? "null");
export const throws = () => {
  throw new TypeError("Failed to fetch");
};
export const button = (name: string | RegExp) => screen.findByRole("button", { name });

/**
 * Puts a number into a field, replacing what is there, as one change event.
 * Typing key by key (or even clear + paste through user-event) re-rendered the
 * page and walked the DOM per step: ~300 ms per field, ~100 s for this file,
 * enough to blow the 1 s findBy timeout when 76 files share four cores. These
 * tests are about what the page does with a value, not about keystrokes.
 * The field is found by its label, which is as strict as the accessible name
 * here and much cheaper than a role query.
 */
export async function enter(label: string, value: string) {
  await enterAll([[label, value]]);
}

/**
 * Several fields at once, committed in one render. Every change re-renders the whole
 * page (~100 ms in jsdom), so six separate changes cost six renders; inside one act the
 * updates are batched. The page keeps its rows with functional updates, so none is lost.
 */
export async function enterAll(pairs: readonly (readonly [string, string])[]) {
  const fields: HTMLElement[] = [];
  for (const [label] of pairs) fields.push(await screen.findByLabelText(label));
  act(() => {
    pairs.forEach(([, value], i) => fireEvent.change(fields[i]!, { target: { value } }));
  });
}

export async function fillThree() {
  const list = [
    ["0,2", "-0,1"],
    ["0,4", "0"],
    ["0,6", "0,3"],
  ] as const;
  const crossings = ["S1 · Z1", "S3 · Z1", "S1 · Z11"];
  await enterAll(crossings.flatMap((c, i) => [[`Across at ${c} (mm)`, list[i]![0]], [`Down at ${c} (mm)`, list[i]![1]]] as const));
}

export const FIT = {
  values: { offset_x_mm: 0.35, offset_y_mm: -0.15, scale_x: 1.0012, scale_y: 0.9995, rotation_deg: 0.03 },
  residuals_mm: [0.05, 0.42, 0.1, 0.02],
  flagged: [1],
  out_of_range: [],
};
