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

/**
 * A tape batch printed in sub-jobs (#277): the batch id for continue and reprint, where each sub-job starts in
 * `jobIds`, the labels of an unknown group the user said printed, and the sub-job the user already continued.
 */
export interface WatchRun {
  batchId: string;
  subJobStarts: number[];
  confirmed: string[];
  continued?: number;
}

/** What the stack shows of a run: 1-based sub-job, whether it waits for the user, the unknown labels (1-based). */
export interface RunView {
  subJob: number;
  subJobs: number;
  awaiting: boolean;
  unknownFrom: number | null;
  unknownTo: number | null;
  /** After a stop: the group's outcome is unknown, or the printer refused it before sending anything. */
  stopKind: "unknown" | "refused" | null;
  /** The labels a reprint may start from (1-based): the unknown group and one past it, or the refused group's first. */
  reprintFrom: number | null;
  reprintTo: number | null;
  /** The error code of the first refused label (the reason in the app's words). */
  stopCode: string | null;
  total: number;
}

interface WatchRecord {
  id: string;
  kind: PrintKind;
  printerId: string | null;
  jobIds: string[];
  run?: WatchRun;
  /**
   * A page line is about to claim this print: the stack does not announce it in the meantime (no double
   * announcement). `true`: waiting for the first claim; a job id: the claim of that job is being handed over to
   * the job that replaced it (a retry). Cleared by the claim arriving, or by whoever was going to claim it
   * going away first (`releaseClaimPending`, the release of the handed-over claim), so it can never stick.
   */
  claimPending?: true | string;
}

const withoutPending = (r: WatchRecord): WatchRecord => ({ id: r.id, kind: r.kind, printerId: r.printerId, jobIds: r.jobIds, ...(r.run ? { run: r.run } : {}) });

/** A watched print with its state worked out from the jobs it holds. */
export interface WatchedPrint extends Omit<WatchRecord, "run"> {
  phase: JobPhase;
  total: number;
  /** Jobs that ended well. */
  finished: number;
  failedJobIds: string[];
  live: Record<string, JobLive | undefined>;
  /** A page shows one of its jobs in its own live line (`claimJob`): the stack shows the card but does not announce it. */
  claimed: boolean;
  /** A tape run in sub-jobs (#277), else undefined; `runBatchId` is its batch for continue and reprint. */
  run?: RunView;
  runBatchId?: string;
}

interface Store {
  records: WatchRecord[];
  live: Record<string, JobLive>;
  /** Insertion order of `live`, to drop the oldest unwatched job state. */
  order: string[];
  /** Jobs a mounted page line shows right now, with how many lines show each. */
  claims: Record<string, number>;
  derived: WatchedPrint[];
}

const UNWATCHED_LIMIT = 200;
const AT_PRINTER = new Set(["waiting", "printing", "stopped"]);
const empty = (): Store => ({ records: [], live: {}, order: [], claims: {}, derived: [] });

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

/**
 * The run's state from the job events alone: the unknown group (`outcome_unknown`, minus what the user confirmed),
 * else the sub-job of the first open label, which waits for the user when it has not begun and is not continued.
 */
function runViewOf(record: WatchRecord, live: Record<string, JobLive>): RunView | undefined {
  const run = record.run;
  if (!run) return undefined;
  const starts = run.subJobStarts.length > 0 ? run.subJobStarts : [0];
  const subJobOf = (index: number) => starts.filter((s) => s <= index).length;
  // A restart failed the waiting labels: the hub no longer holds the run, so it offers no actions.
  if (record.jobIds.some((id) => live[id]?.errorCode === "tape_run_interrupted")) return undefined;
  const confirmed = new Set(run.confirmed);
  const total = record.jobIds.length;
  const calm = { awaiting: false, unknownFrom: null, unknownTo: null, stopKind: null, reprintFrom: null, reprintTo: null, stopCode: null, total };
  const unknown = record.jobIds.flatMap((id, i) => (live[id]?.errorCode === "outcome_unknown" && !confirmed.has(id) ? [i] : []));
  if (unknown.length > 0) {
    const from = unknown[0]! + 1;
    const to = unknown.at(-1)! + 1;
    return { ...calm, subJob: subJobOf(unknown[0]!), subJobs: starts.length, unknownFrom: from, unknownTo: to, stopKind: "unknown", reprintFrom: from, reprintTo: to + 1, stopCode: "outcome_unknown" };
  }
  const phaseAt = (i: number) => live[record.jobIds[i]!]?.phase ?? "queued";
  // Nothing unknown but a label failed: the printer refused a group before sending anything (#277).
  const refused = record.jobIds.findIndex((id, i) => !confirmed.has(id) && phaseAt(i) === "failed");
  if (refused >= 0) {
    const code = live[record.jobIds[refused]!]?.errorCode ?? null;
    return { ...calm, subJob: subJobOf(refused), subJobs: starts.length, stopKind: "refused", reprintFrom: refused + 1, reprintTo: refused + 1, stopCode: code };
  }
  const firstOpen = record.jobIds.findIndex((_, i) => !confirmed.has(record.jobIds[i]!) && !isTerminal(phaseAt(i)));
  if (firstOpen < 0) return { ...calm, subJob: starts.length, subJobs: starts.length };
  const subJob = subJobOf(firstOpen);
  const end = starts[subJob] ?? record.jobIds.length;
  const notBegun = record.jobIds.slice(starts[subJob - 1]!, end).every((_, k) => phaseAt(starts[subJob - 1]! + k) === "queued");
  const awaiting = subJob > 1 && firstOpen === starts[subJob - 1] && notBegun && run.continued !== subJob;
  return { ...calm, subJob, subJobs: starts.length, awaiting };
}

function derive(records: WatchRecord[], live: Record<string, JobLive>, claims: Record<string, number>): WatchedPrint[] {
  return records.map((record) => {
    // Labels of an unknown group the user confirmed (a reprint) count as printed.
    const confirmed = new Set(record.run?.confirmed ?? []);
    const phases = record.jobIds.map((id) => (confirmed.has(id) ? "done" : (live[id]?.phase ?? "queued")));
    const failedJobIds = record.jobIds.filter((_, i) => phases[i] === "failed");
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
    const { run: tapeRun, ...rest } = record;
    const view = tapeRun ? runViewOf(record, live) : undefined;
    return {
      ...rest,
      phase,
      total: record.jobIds.length,
      finished,
      failedJobIds,
      live: Object.fromEntries(record.jobIds.map((id) => [id, live[id]])),
      claimed: record.claimPending !== undefined || record.jobIds.some((id) => (claims[id] ?? 0) > 0),
      ...(view ? { run: view, runBatchId: tapeRun!.batchId } : {}),
    };
  });
}

function commit(next: { records?: WatchRecord[]; live?: Record<string, JobLive>; order?: string[]; claims?: Record<string, number>; keepDerived?: boolean }): void {
  const records = next.records ?? store.records;
  const live = next.live ?? store.live;
  const claims = next.claims ?? store.claims;
  store = { records, live, order: next.order ?? store.order, claims, derived: next.keepDerived ? store.derived : derive(records, live, claims) };
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
    const watched = new Set([...store.records.flatMap((r) => r.jobIds), ...Object.keys(store.claims)]);
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
export function watchPrint(input: { kind: PrintKind; printerId: string | null; jobIds: string[]; claimPending?: boolean; run?: WatchRun }): string {
  const id = `print-${++counter}`;
  if (input.jobIds.length === 0) return id;
  const record: WatchRecord = { id, kind: input.kind, printerId: input.printerId, jobIds: [...input.jobIds] };
  if (input.claimPending) record.claimPending = true;
  if (input.run) record.run = { ...input.run, subJobStarts: [...input.run.subJobStarts], confirmed: [...input.run.confirmed] };
  commit({ records: [...store.records, record] });
  return id;
}

/**
 * A page that shows a job in its own live line claims it: the stack keeps the card but stops announcing it
 * (one announcement per state change), and a reconnect resync reads the job even after its card was
 * dismissed. Returns the release; call it when the line goes away or follows another job.
 */
export function claimJob(jobId: string): () => void {
  // The claim a print registered with `claimPending` was waiting for has arrived.
  const waiting = (r: WatchRecord) => r.claimPending !== undefined && r.jobIds.includes(jobId);
  const settled = store.records.some(waiting) ? store.records.map((r) => (waiting(r) ? withoutPending(r) : r)) : undefined;
  commit({ claims: { ...store.claims, [jobId]: (store.claims[jobId] ?? 0) + 1 }, ...(settled ? { records: settled } : {}) });
  let released = false;
  return () => {
    if (released) return;
    released = true;
    const claims = { ...store.claims };
    const left = (claims[jobId] ?? 0) - 1;
    if (left > 0) claims[jobId] = left;
    else delete claims[jobId];
    // A claim that was being handed over from this job to its replacement will not arrive any more.
    const handedOver = store.records.some((r) => r.claimPending === jobId);
    commit({ claims, ...(handedOver ? { records: store.records.map((r) => (r.claimPending === jobId ? withoutPending(r) : r)) } : {}) });
  };
}

/** The registrant of a `claimPending` print went away before any line claimed it: nobody will, so the stack announces it again. */
export function releaseClaimPending(jobId: string): void {
  if (!store.records.some((r) => r.claimPending === true && r.jobIds.includes(jobId))) return;
  commit({ records: store.records.map((r) => (r.claimPending === true && r.jobIds.includes(jobId) ? withoutPending(r) : r)) });
}

/** The watched print that holds this job right now, or undefined (never registered, or already dismissed). */
export const watchedPrintOfJob = (jobId: string): WatchedPrint | undefined => store.derived.find((e) => e.jobIds.includes(jobId));

export function dismissWatch(id: string): void {
  commit({ records: store.records.filter((r) => r.id !== id) });
}

/**
 * Watches an accepted tape batch (#277): every label (copies included) and the run, so the stack can show the
 * sub-jobs, the confirmation between them and a reprint after a stop.
 */
export function watchBatch(kind: PrintKind, accepted: { batch_id: string; printer_id: string; job_ids: string[]; label_job_ids?: string[]; sub_job_size: number }): string {
  const jobIds = accepted.label_job_ids && accepted.label_job_ids.length > 0 ? accepted.label_job_ids : accepted.job_ids;
  return watchPrint({
    kind,
    printerId: accepted.printer_id,
    jobIds,
    run: { batchId: accepted.batch_id, subJobStarts: subJobStartsOf(jobIds.length, accepted.sub_job_size), confirmed: [] },
  });
}

/** The sub-jobs of a tape batch: one every `size` labels (the server's split, #277). */
export const subJobStartsOf = (count: number, size: number): number[] =>
  Array.from({ length: Math.max(1, Math.ceil(count / Math.max(1, size))) }, (_, i) => i * size);

/** A reprint from label N (#277): the run's labels in their new order, what the user confirmed, the new split. */
export function replaceRunJobs(entryId: string, next: { jobIds: string[]; confirmed: string[]; subJobStarts: number[] }): void {
  commit({
    records: store.records.map((r) =>
      r.id === entryId && r.run
        ? { ...r, jobIds: [...next.jobIds], run: { batchId: r.run.batchId, subJobStarts: [...next.subJobStarts], confirmed: [...new Set([...r.run.confirmed, ...next.confirmed])] } }
        : r,
    ),
  });
}

/** The user continued sub-job `subJob` (1-based): the stack stops offering it while the worker picks it up. */
export function markRunContinued(entryId: string, subJob: number): void {
  commit({ records: store.records.map((r) => (r.id === entryId && r.run ? { ...r, run: { ...r.run, continued: subJob } } : r)) });
}

/*
 * The same run can be acted on from the stack and from the jobs page: these find every watched print of a batch,
 * so a card never keeps buttons for something done elsewhere (#277).
 */
const ofBatch = (batchId: string) => store.records.filter((r) => r.run?.batchId === batchId).map((r) => r.id);

/** Sub-job `subJob` of the batch was continued (anywhere). */
export function runContinued(batchId: string, subJob: number): void {
  ofBatch(batchId).forEach((id) => markRunContinued(id, subJob));
}

/** The batch was reprinted (anywhere): its cards follow the new jobs. */
export function runReprinted(batchId: string, next: { jobIds: string[]; confirmed: string[]; subJobStarts: number[] }): void {
  ofBatch(batchId).forEach((id) => replaceRunJobs(id, next));
}

/** The batch was discarded (anywhere): its cards go. */
export function runDiscarded(batchId: string): void {
  const ids = new Set(ofBatch(batchId));
  if (ids.size > 0) commit({ records: store.records.filter((r) => !ids.has(r.id)) });
}

/**
 * The hub no longer knows the run (a restart, a discard in another browser): its cards keep the jobs but lose the
 * run's actions, so nothing offers Continue or Reprint for a run that is gone.
 */
export function forgetRun(batchId: string): void {
  const ids = new Set(ofBatch(batchId));
  if (ids.size > 0) commit({ records: store.records.map((r) => (ids.has(r.id) ? withoutRun(r) : r)) });
}

const withoutRun = (r: WatchRecord): WatchRecord => {
  const next = { ...r };
  delete next.run;
  return next;
};

/** A retry clones a failed job into a new queued one: the entry follows the new job. */
export function replaceWatchedJob(entryId: string, oldJobId: string, newJobId: string): void {
  // A page line that claims the old job will claim the new one next: until it has, the card stays claimed (no
  // moment in the announced lists, so no second announcement).
  const handOver = (store.claims[oldJobId] ?? 0) > 0;
  commit({
    records: store.records.map((r) =>
      r.id === entryId ? { ...r, jobIds: r.jobIds.map((j) => (j === oldJobId ? newJobId : j)), ...(handOver ? { claimPending: oldJobId } : {}) } : r,
    ),
  });
}

/**
 * After the stream came back: a job that ended while it was down sent a frame nobody saw. Every watched
 * job that is not finished is read once. A failed read keeps the state we had.
 */
export async function resyncWatchedJobs(read: (jobId: string) => Promise<{ state: string; error?: string | null }>): Promise<void> {
  const open = [...new Set([...store.records.flatMap((r) => r.jobIds), ...Object.keys(store.claims)])].filter((id) => !isTerminal(store.live[id]?.phase ?? "queued"));
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
