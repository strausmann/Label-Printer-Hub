import type { Job } from "./api";

type Json = Record<string, unknown>;
const obj = (v: unknown): Json => (typeof v === "object" && v !== null && !Array.isArray(v) ? (v as Json) : {});
const text = (v: unknown): string | null => (typeof v === "string" && v.trim() !== "" ? v : typeof v === "number" ? String(v) : null);

export interface PayloadSummary {
  title: string | null;
  code: string | null;
  source: string | null;
  contentType: string | null;
  tapeMm: number | null;
  copies: number | null;
  copyIndex: number | null;
  copyTotal: number | null;
}

/** Reads the fields the print service stores in `payload`; anything missing stays null. */
export function summarizePayload(job: Job): PayloadSummary {
  const p = obj(job.payload);
  const label = obj(p.label_data);
  const options = obj(p.options);
  const tape = p.tape_mm ?? p.rendered_tape_mm;
  const num = (v: unknown) => (typeof v === "number" ? v : null);
  return {
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

/** What the person calls this job: the label's title, else its code, else the template. */
export function jobTitle(job: Job): string | null {
  const s = summarizePayload(job);
  return s.title ?? s.code ?? job.template_key;
}

export const canRetry = (job: Job) => job.state === "failed" || job.state === "failed_restart";
/** Only a waiting job: a printing one is already on the wire. */
export const canCancel = (job: Job) => job.state === "queued";

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
