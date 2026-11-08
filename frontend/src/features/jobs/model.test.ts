import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { initI18n } from "../../i18n";
import { job } from "../test-api";
import { canCancel, canRetry, jobTitle, pageInfoOf, summarizePayload } from "./model";

beforeAll(() => initI18n("en"));

const P = "dddddddd-0000-4000-8000-000000000009";
const sheetPage = (over: Record<string, unknown> = {}, state = "queued") =>
  job("j1", P, state, {
    template_key: null,
    payload: {
      kind: "sheet_page",
      job_name: "ignored",
      detail: { sheet_code: "L4736-0002", cells: [{ cell: 3 }, { cell: 4 }], id_cell: { cell: 1 }, job_summary: { sheet_code: "L4736-0002", cell_count: 9 } },
    },
    ...over,
  });
const calibration = (detail: Record<string, unknown> = { type_key: "L4736REV", version: 1, printer_name: "Office" }) =>
  job("j2", P, "queued", { template_key: null, payload: { kind: "calibration_page", detail } });

describe("jobTitle for page jobs", () => {
  it("names a sheet page by its code and the number of labels", () => {
    expect(jobTitle(sheetPage() as never)).toBe("Sheet L4736-0002 · 9 labels");
  });

  it("uses the singular for one label and counts the cells when the summary is missing", () => {
    const one = sheetPage({ payload: { kind: "sheet_page", detail: { sheet_code: "L4736-0002", job_summary: { cell_count: 1 } } } });
    expect(jobTitle(one as never)).toBe("Sheet L4736-0002 · 1 label");
    const noSummary = sheetPage({ payload: { kind: "sheet_page", detail: { sheet_code: "L4736-0002", cells: [{ cell: 1 }, { cell: 2 }] } } });
    expect(jobTitle(noSummary as never)).toBe("Sheet L4736-0002 · 2 labels");
  });

  it("takes the code from the summary when the detail has none, and stays sensible without any", () => {
    const fromSummary = sheetPage({ payload: { kind: "sheet_page", detail: { sheet_code: null, job_summary: { sheet_code: "L4736-0005", cell_count: 4 } } } });
    expect(jobTitle(fromSummary as never)).toBe("Sheet L4736-0005 · 4 labels");
    const bare = sheetPage({ payload: { kind: "sheet_page", detail: {} } });
    expect(jobTitle(bare as never)).toBe("Sheet page");
  });

  it("names a calibration page by sheet type and version", () => {
    expect(jobTitle(calibration() as never)).toBe("Calibration page · L4736REV v1");
    expect(jobTitle(calibration({}) as never)).toBe("Calibration page");
  });

  it("leaves a tape job as it was", () => {
    const tape = job("t", P, "done", { template_key: "asset-label", payload: { label_data: { title: "Cordless drill", primary_id: "A-0042" } } });
    expect(jobTitle(tape as never)).toBe("Cordless drill");
    const noTitle = job("t", P, "done", { template_key: "asset-label", payload: { label_data: { primary_id: "A-0042" } } });
    expect(jobTitle(noTitle as never)).toBe("A-0042");
    expect(jobTitle(job("t", P, "done", { payload: {} }) as never)).toBe("asset-label");
    expect(summarizePayload(tape as never).page).toBeNull();
  });
});

describe("pageInfoOf", () => {
  it("reads the sheet, the cells and the ID cell of a sheet page", () => {
    expect(pageInfoOf(sheetPage() as never)).toMatchObject({ kind: "sheet_page", sheetCode: "L4736-0002", cells: [3, 4], idCell: 1, cellCount: 9 });
  });

  it("is null for a tape job and ignores values of the wrong shape", () => {
    expect(pageInfoOf(job("t", P, "done", { payload: {} }) as never)).toBeNull();
    const odd = sheetPage({ payload: { kind: "sheet_page", detail: { sheet_code: 7, cells: "x", id_cell: "y", job_summary: { cell_count: "9" } } } });
    expect(pageInfoOf(odd as never)).toMatchObject({ sheetCode: null, cells: [], idCell: null, cellCount: 0 });
  });
});

describe("canRetry and canCancel", () => {
  it("retries failed jobs, and cancelled page jobs too", () => {
    const tape = (s: string) => job("t", P, s, { payload: {} }) as never;
    expect([canRetry(tape("failed")), canRetry(tape("failed_restart")), canRetry(tape("cancelled")), canRetry(tape("done"))]).toEqual([true, true, false, false]);
    expect([canRetry(sheetPage({}, "failed") as never), canRetry(sheetPage({}, "cancelled") as never), canRetry(sheetPage({}, "failed_restart") as never)]).toEqual([true, true, true]);
    expect(canRetry(calibration() as never)).toBe(false); // queued
    expect(canRetry({ ...calibration(), state: "cancelled" } as never)).toBe(true);
  });

  it("does not offer a retry for a finished sheet page: its labels came out", () => {
    expect(canRetry(sheetPage({}, "done") as never)).toBe(false);
  });

  it("cancels a waiting job, and a printing one only when it is a page job", () => {
    const tape = (s: string) => job("t", P, s, { payload: {} }) as never;
    expect([canCancel(tape("queued")), canCancel(tape("printing")), canCancel(tape("failed"))]).toEqual([true, false, false]);
    expect([canCancel(sheetPage({}, "printing") as never), canCancel(sheetPage({}, "queued") as never), canCancel(sheetPage({}, "done") as never)]).toEqual([true, true, false]);
    expect(canCancel({ ...calibration(), state: "printing" } as never)).toBe(true);
  });
});

describe("jobTitle in German", () => {
  beforeAll(() => initI18n("de"));
  afterAll(() => initI18n("en"));

  it("names both page kinds in German", () => {
    expect(jobTitle(sheetPage() as never)).toBe("Bogen L4736-0002 · 9 Etiketten");
    expect(jobTitle(calibration() as never)).toBe("Kalibrierseite · L4736REV v1");
  });
});
