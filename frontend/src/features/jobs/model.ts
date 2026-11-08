import { plural, t } from "@lingui/core/macro";
import type { Job } from "./api";

type Json = Record<string, unknown>;
const obj = (v: unknown): Json => (typeof v === "object" && v !== null && !Array.isArray(v) ? (v as Json) : {});
const text = (v: unknown): string | null => (typeof v === "string" && v.trim() !== "" ? v : typeof v === "number" ? String(v) : null);

export type PageKind = "sheet_page" | "calibration_page";

/** What a page job (a sheet page or a calibration page) stores in `payload.detail` and `job_summary`. */
export interface PageInfo {
  kind: PageKind;
  /** The sheet the page prints onto; null for a calibration page, or when the payload has none. */
  sheetCode: string | null;
  /** The cells the page labels, without the ID cell. */
  cells: number[];
  idCell: number | null;
  /** Labels on the page: the summary's count, else the cells listed. */
  cellCount: number;
  /** Calibration page: the sheet type and version it was drawn for. */
  typeKey: string | null;
  version: number | null;
}

export interface PayloadSummary {
  page: PageInfo | null;
  title: string | null;
  code: string | null;
  source: string | null;
  contentType: string | null;
  tapeMm: number | null;
  copies: number | null;
  copyIndex: number | null;
  copyTotal: number | null;
}

const num = (v: unknown): number | null => (typeof v === "number" ? v : null);
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() !== "" ? v : null);

function cellNumbers(list: unknown): number[] {
  if (!Array.isArray(list)) return [];
  return list.flatMap((c) => {
    const n = num(obj(c).cell);
    return n === null ? [] : [n];
  });
}

/** The page-job part of a payload, or null for a tape job. Values of the wrong shape count as missing. */
export function pageInfoOf(job: Job): PageInfo | null {
  const p = obj(job.payload);
  if (p.kind !== "sheet_page" && p.kind !== "calibration_page") return null;
  const detail = obj(p.detail);
  const summary = obj(detail.job_summary);
  const cells = cellNumbers(detail.cells);
  const idCell = num(obj(detail.id_cell).cell);
  return {
    kind: p.kind,
    sheetCode: str(detail.sheet_code) ?? str(summary.sheet_code),
    cells,
    idCell,
    cellCount: num(summary.cell_count) ?? cells.length,
    typeKey: str(detail.type_key),
    version: num(detail.version),
  };
}

/** Reads the fields the print service stores in `payload`; anything missing stays null. */
export function summarizePayload(job: Job): PayloadSummary {
  const p = obj(job.payload);
  const label = obj(p.label_data);
  const options = obj(p.options);
  const tape = p.tape_mm ?? p.rendered_tape_mm;
  return {
    page: pageInfoOf(job),
    title: text(label.title),
    code: text(label.primary_id),
    source: text(label.source_app),
    contentType: text(p.content_type),
    tapeMm: num(tape),
    copies: num(options.copies),
    copyIndex: num(p.copy_index),
    copyTotal: num(p.copy_total),
  };
}

/** "Sheet L4736-0002 · 9 labels", "Calibration page · L4736REV v1". */
function pageTitle(page: PageInfo): string {
  if (page.kind === "calibration_page") {
    if (page.typeKey === null) return t`Calibration page`;
    const version = page.version === null ? "" : ` v${page.version}`;
    return t`Calibration page · ${page.typeKey}${version}`;
  }
  if (page.sheetCode === null) return t`Sheet page`;
  const code = page.sheetCode;
  const labels = plural(page.cellCount, { one: "# label", other: "# labels" });
  return t`Sheet ${code} · ${labels}`;
}

/** What the person calls this job: the page, else the label's title, else its code, else the template. */
export function jobTitle(job: Job): string | null {
  const s = summarizePayload(job);
  if (s.page) return pageTitle(s.page);
  return s.title ?? s.code ?? job.template_key;
}

/** A tape job fails or is retried as it always was; a page job can also be retried once cancelled (a stuck page, stopped at the printer). */
export function canRetry(job: Job): boolean {
  if (job.state === "failed" || job.state === "failed_restart") return true;
  // A finished sheet page is not retried: its labels came out.
  return job.state === "cancelled" && pageInfoOf(job) !== null;
}

/** A waiting job; a page job is also cancelled while it is at the printer (the printer is asked to). A tape job in print is on the wire. */
export const canCancel = (job: Job): boolean =>
  job.state === "queued" || (job.state === "printing" && pageInfoOf(job) !== null);

export interface HistoryStep {
  state: "queued" | "printing" | "finished";
  at: string;
}

/** The job row keeps no event log, only its timestamps: created, started, finished. */
export function historyOf(job: Job): HistoryStep[] {
  const steps: HistoryStep[] = [{ state: "queued", at: job.created_at }];
  if (job.started_at) steps.push({ state: "printing", at: job.started_at });
  if (job.finished_at) steps.push({ state: "finished", at: job.finished_at });
  return steps;
}

export const JOB_FILTERS = ["all", "queued", "printing", "done", "failed", "cancelled"] as const;
export type JobFilter = (typeof JOB_FILTERS)[number];

export const formatTime = (iso: string) => {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString([], { dateStyle: "short", timeStyle: "short" });
};
