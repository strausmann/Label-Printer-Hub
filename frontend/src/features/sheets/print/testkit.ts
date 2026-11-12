import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect } from "vitest";
import type { components } from "../../../api/schema.gen";
import {
  GEOMETRY_L4736,
  PAGE_PRINTER,
  PRINTED_PAGE,
  PRINTER_A,
  SHEET_TYPE,
  apiErrorBody,
  pageStatus,
  respond,
  sheetPreview,
  sheetRead,
  sheetSummary,
  status,
} from "../../test-api";

type Schemas = components["schemas"];
export const P = PAGE_PRINTER.id;
export const JOB = PRINTED_PAGE.job_id;
export const BATCH = "cccccccc-0000-4000-8000-000000000009";

export const GROCY_ITEM = { app: "grocy", id: "7", name: "Flour", url: "https://grocy.example.invalid/product/7", extra: {} };

export const reason = (keyword: string, severity: "report" | "warning" | "error", blocking: boolean) => ({ keyword, severity, blocking });

/** A sheet the way the list answers it: `used` of 48 cells taken. */
export const sheet = (code: string, used: number, over: Partial<Schemas["SheetSummary"]> = {}) =>
  sheetSummary(code, { used, free: 48 - used, ...over });

/** One preview page of a 48-cell sheet: `fresh` cells are new, `used` ones taken, the rest free. */
export function previewPage(code: string | null, fresh: number[], used: number[] = [], over: Partial<Schemas["PreviewPage"]> = {}): Schemas["PreviewPage"] {
  const base = sheetPreview().pages[0]!;
  return {
    ...base,
    sheet_code: code,
    new_code_hint: code ? null : "L4736-0005",
    cells: Array.from({ length: 48 }, (_, i) => {
      const cell = i + 1;
      const index = fresh.indexOf(cell);
      return {
        cell,
        state: index >= 0 ? ("new" as const) : used.includes(cell) ? ("used" as const) : ("free" as const),
        item_index: index >= 0 ? index : null,
        purpose: index >= 0 ? `Flour ${index + 1}` : used.includes(cell) ? `Grocy · item ${cell}` : null,
        is_id: false,
        hw_margin: false,
        mapped: false,
        truncated: false,
      };
    }),
    ...over,
  };
}

export function previewFor(code: string | null, fresh: number[], used: number[] = [], over: Partial<Schemas["SheetPreview"]> = {}, page: Partial<Schemas["PreviewPage"]> = {}): Schemas["SheetPreview"] {
  return sheetPreview({
    pages: [previewPage(code, fresh, used, page)],
    free_after: [48 - used.length - fresh.length],
    expected_cells: [{ sheet: code ?? "new", cells: fresh, id_cell: null }],
    reprint_hints: [],
    placed: fresh.length,
    remaining: 0,
    ...over,
  });
}

const range = (from: number, to: number) => Array.from({ length: to - from + 1 }, (_, i) => from + i);
export const USED_17 = range(1, 17);
export const NEW_9 = range(18, 26);

export interface RouteOptions {
  printers?: unknown[];
  status?: Schemas["PrinterStatus"];
  sheets?: Schemas["SheetSummary"][];
  preview?: unknown;
  print?: unknown;
  types?: unknown[];
  extra?: Record<string, unknown>;
}

export function routes(o: RouteOptions = {}): Record<string, unknown> {
  const sheets = o.sheets ?? [sheet("L4736-0001", 17)];
  return {
    "GET /api/v1/lookup/grocy/7": GROCY_ITEM,
    "GET /api/v1/printers": o.printers ?? [PAGE_PRINTER, PRINTER_A],
    [`GET /api/v1/printers/${P}/status`]: o.status ?? pageStatus(P),
    [`GET /api/v1/printers/${PRINTER_A.id}/status`]: status(PRINTER_A.id),
    "POST /api/v1/render/preview": () => new Response(new Uint8Array([137, 80, 78, 71]), { status: 200, headers: { "Content-Type": "image/png" } }),
    // Like the server: an archived type is left out unless the request asks for it (`include_archived=true`).
    "GET /api/v1/sheet-types": (_init: RequestInit, url: URL) =>
      (o.types ?? [SHEET_TYPE]).filter((t) => url.searchParams.get("include_archived") === "true" || !(t as { archived_at?: string | null }).archived_at),
    "GET /api/v1/sheets": sheets,
    "GET /api/v1/sheets/next-code": { code: "L4736-0005", hint: "probable" },
    ...Object.fromEntries(sheets.map((s) => [`GET /api/v1/sheets/${s.code}`, sheetRead(s.code, { used: USED_17 }, { used: s.used, free: s.free })])),
    [`POST /api/v1/print/${P}/sheet/preview`]: o.preview ?? previewFor("L4736-0001", NEW_9, USED_17),
    [`POST /api/v1/print/${P}/sheet`]: o.print ?? { batch_id: BATCH, pages: [{ ...PRINTED_PAGE, cells: NEW_9 }], placed: NEW_9.length, remaining: 0 },
    ...o.extra,
  };
}

export const conflict = (status: number, code: string, message: string, detail?: Record<string, unknown>) => respond(status, apiErrorBody(code, message, detail));

export const body = (call: { body: string | undefined }) => JSON.parse(call.body!) as Schemas["SheetPrintRequest"];

/** Opens a react-aria select and takes the option. */
export async function pick(label: string | RegExp, option: string | RegExp) {
  await userEvent.click(screen.getByRole("button", { name: label }));
  await userEvent.click(await screen.findByRole("option", { name: option }));
}

/** The sheet type field: a combobox whose text is the chosen type. */
export const typeBox = async () => (await screen.findByRole("combobox", { name: "Sheet type" })) as HTMLInputElement;

/** Waits until the sheet type field shows the type; it can arrive after a fetch or an event. */
export async function expectType(text: RegExp, timeout?: number) {
  await waitFor(async () => expect((await typeBox()).value).toMatch(text), timeout ? { timeout } : undefined);
}

export async function pickType(option: string | RegExp) {
  await userEvent.click(await typeBox());
  await userEvent.click(await screen.findByRole("option", { name: option }));
}

export { GEOMETRY_L4736 };
