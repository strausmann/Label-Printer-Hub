import { useSyncExternalStore } from "react";

/*
 * One live source for "where is my print": every print action registers the jobs it queued
 * (`watchPrint`), the SSE hook feeds every `job.state_changed` frame in (`recordJobEvent`), and the
 * notification stack in the shell and the calibration page both read it back. No polling: after a
 * reconnect the open jobs are read once (`resyncWatchedJobs`).
 *
 * Interfaces for readers: `useWatchedPrints()` (all entries), `useJobLive(jobId)` (one job).
 */

export type PrintKind = "item" | "cart" | "sheet" | "calibration" | "test";
export type JobPhase = "queued" | "paused" | "printing" | "done" | "failed" | "cancelled";

/**
 * What the events say about one job. There is deliberately no queue position: the events carry only the
 * count of ALL open jobs of the printer (those behind this job included), which is not "jobs ahead".
 */
export interface JobLive {
  phase: JobPhase;
  /** Page jobs only: `waiting` / `printing` / `stopped` at the printer. */
  atPrinter: "waiting" | "printing" | "stopped" | null;
  atPrinterReasons: string[];
  errorCode: string | null;
}

/** The code a job record's `error` starts with (`ipp_aborted: The printer aborted ...`), or null. */
export const errorCodeFromMessage = (message: string | null | undefined): string | null =>
  /^([a-z][a-z0-9_-]*): /.exec(message ?? "")?.[1] ?? null;

interface WatchRecord {
  id: string;
  kind: PrintKind;
  printerId: string | null;
  jobIds: string[];
}

/** A watched print with its state worked out from the jobs it holds. */
export interface WatchedPrint extends WatchRecord {
  phase: JobPhase;
  total: number;
  /** Jobs that ended well. */
  finished: number;
  failedJobIds: string[];
  live: Record<string, JobLive | undefined>;
}

interface Store {
  records: WatchRecord[];
  live: Record<string, JobLive>;
  /** Insertion order of `live`, to drop the oldest unwatched job state. */
  order: string[];
  derived: WatchedPrint[];
}

const UNWATCHED_LIMIT = 200;
const AT_PRINTER = new Set(["waiting", "printing", "stopped"]);
const empty = (): Store => ({ records: [], live: {}, order: [], derived: [] });

let store: Store = empty();
const listeners = new Set<() => void>();
let counter = 0;

const phaseOf = (state: unknown): JobPhase => {
  switch (state) {
    case "printing":
      return "printing";
    // The queue's events say `completed`, the job record says `done`.
    case "completed":
    case "done":
      return "done";
    case "failed":
    case "failed_restart":
      return "failed";
    case "cancelled":
      return "cancelled";
    case "paused":
      return "paused";
    default:
      return "queued";
  }
};
const isTerminal = (phase: JobPhase) => phase === "done" || phase === "failed" || phase === "cancelled";

function derive(records: WatchRecord[], live: Record<string, JobLive>): WatchedPrint[] {
  return records.map((record) => {
    const phases = record.jobIds.map((id) => live[id]?.phase ?? "queued");
    const failedJobIds = record.jobIds.filter((id) => live[id]?.phase === "failed");
    const finished = phases.filter((p) => p === "done").length;
    const open = phases.some((p) => !isTerminal(p));
    let phase: JobPhase;
    if (open) {
      const waiting = phases.filter((p) => !isTerminal(p));
      if (phases.some((p) => p === "printing") || finished > 0) phase = "printing";
      else phase = waiting.every((p) => p === "paused") ? "paused" : "queued";
    }
    else if (failedJobIds.length > 0) phase = "failed";
    else if (finished === 0) phase = "cancelled";
    else phase = "done";
    return { ...record, phase, total: record.jobIds.length, finished, failedJobIds, live: Object.fromEntries(record.jobIds.map((id) => [id, live[id]])) };
  });
}

function commit(next: { records?: WatchRecord[]; live?: Record<string, JobLive>; order?: string[]; keepDerived?: boolean }): void {
  const records = next.records ?? store.records;
  const live = next.live ?? store.live;
  store = { records, live, order: next.order ?? store.order, derived: next.keepDerived ? store.derived : derive(records, live) };
  listeners.forEach((l) => l());
}

const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => void listeners.delete(listener);
};

function setLive(jobId: string, value: JobLive): void {
  const known = jobId in store.live;
  let order = known ? store.order : [...store.order, jobId];
  let live = { ...store.live, [jobId]: value };
  if (order.length > UNWATCHED_LIMIT) {
    const watched = new Set(store.records.flatMap((r) => r.jobIds));
    const drop = order.find((id) => !watched.has(id));
    if (drop) {
      order = order.filter((id) => id !== drop);
      live = Object.fromEntries(Object.entries(live).filter(([id]) => id !== drop));
    }
  }
  // A job nobody watches changes no entry: the stack keeps its snapshot and does not re-render on that traffic.
  const watchedNow = store.records.some((r) => r.jobIds.includes(jobId));
  commit({ live, order, keepDerived: !watchedNow });
}

/** Feeds one `job.state_changed` payload (the frame's `data`) in. Anything without a job id is ignored. */
export function recordJobEvent(data: Record<string, unknown>): void {
  if (typeof data.job_id !== "string" || data.job_id === "") return;
  const reasons = Array.isArray(data.at_printer_reasons) && data.at_printer_reasons.every((r) => typeof r === "string");
  setLive(data.job_id, {
    phase: phaseOf(data.to_state),
    atPrinter: typeof data.at_printer === "string" && AT_PRINTER.has(data.at_printer) ? (data.at_printer as JobLive["atPrinter"]) : null,
    atPrinterReasons: reasons ? (data.at_printer_reasons as string[]) : [],
    errorCode: typeof data.error_code === "string" ? data.error_code : null,
  });
}

/** Registers the jobs one print action queued; returns the entry id. Several concurrent prints are separate entries. */
export function watchPrint(input: { kind: PrintKind; printerId: string | null; jobIds: string[] }): string {
  const id = `print-${++counter}`;
  if (input.jobIds.length === 0) return id;
  commit({ records: [...store.records, { id, kind: input.kind, printerId: input.printerId, jobIds: [...input.jobIds] }] });
  return id;
}

/** The watched print that holds this job right now, or undefined (never registered, or already dismissed). */
export const watchedPrintOfJob = (jobId: string): WatchedPrint | undefined => store.derived.find((e) => e.jobIds.includes(jobId));

export function dismissWatch(id: string): void {
  commit({ records: store.records.filter((r) => r.id !== id) });
}

/** A retry clones a failed job into a new queued one: the entry follows the new job. */
export function replaceWatchedJob(entryId: string, oldJobId: string, newJobId: string): void {
  commit({ records: store.records.map((r) => (r.id === entryId ? { ...r, jobIds: r.jobIds.map((j) => (j === oldJobId ? newJobId : j)) } : r)) });
}

/**
 * After the stream came back: a job that ended while it was down sent a frame nobody saw. Every watched
 * job that is not finished is read once. A failed read keeps the state we had.
 */
export async function resyncWatchedJobs(read: (jobId: string) => Promise<{ state: string; error?: string | null }>): Promise<void> {
  const open = [...new Set(store.records.flatMap((r) => r.jobIds))].filter((id) => !isTerminal(store.live[id]?.phase ?? "queued"));
  await Promise.all(
    open.map(async (jobId) => {
      try {
        const job = await read(jobId);
        const before = store.live[jobId];
        if (before && isTerminal(before.phase)) return;
        // A frame that came in while the read was out is newer than the answer: a finished job stays finished.
        const phase = phaseOf(job.state);
        setLive(jobId, {
          atPrinter: null,
          atPrinterReasons: [],
          errorCode: phase === "failed" ? errorCodeFromMessage(job.error) : null,
          ...before,
          phase,
        });
      } catch {
        // Keep what the events said; the next frame or reconnect corrects it.
      }
    }),
  );
}

/** Back to an empty store: sign-out, a session that ended, another user behind the same cookie (and every test). */
export function resetPrintWatch(): void {
  counter = 0;
  commit(empty());
}

const getSnapshot = () => store.derived;

/** Every watched print, oldest first. */
export const useWatchedPrints = (): WatchedPrint[] => useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

/** The live state of one job (e.g. the calibration page's job), or undefined while no event has been seen. */
export function useJobLive(jobId: string | null | undefined): JobLive | undefined {
  return useSyncExternalStore(
    subscribe,
    () => (jobId ? store.live[jobId] : undefined),
    () => undefined,
  );
}
