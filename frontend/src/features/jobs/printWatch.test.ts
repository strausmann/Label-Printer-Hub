// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  claimJob,
  dismissWatch,
  errorCodeFromMessage,
  forgetRun,
  markRunContinued,
  recordJobEvent,
  releaseClaimPending,
  replaceRunJobs,
  replaceWatchedJob,
  resetPrintWatch,
  resyncWatchedJobs,
  runContinued,
  runDiscarded,
  runReprinted,
  useJobLive,
  useWatchedPrints,
  watchedPrintOfJob,
  watchPrint,
} from "./printWatch";

const A = "aaaaaaaa-0000-4000-8000-000000000001";
const B = "aaaaaaaa-0000-4000-8000-000000000002";
const C = "aaaaaaaa-0000-4000-8000-000000000003";
const P = "11111111-1111-4111-8111-111111111111";

const event = (jobId: string, to: string, extra: Record<string, unknown> = {}) =>
  recordJobEvent({ job_id: jobId, from_state: "queued", to_state: to, queue_depth: 0, error_code: null, ...extra });

beforeEach(() => resetPrintWatch());

describe("print watch store", () => {
  it("follows one job queued -> printing -> done", () => {
    const { result } = renderHook(() => useWatchedPrints());
    act(() => void watchPrint({ kind: "item", printerId: P, jobIds: [A] }));
    expect(result.current[0]!.phase).toBe("queued");
    act(() => event(A, "printing"));
    expect(result.current[0]!.phase).toBe("printing");
    act(() => event(A, "done"));
    expect(result.current[0]!.phase).toBe("done");
  });

  it("reads the queue's own words: an event says `completed` where the job record says `done`", () => {
    const { result } = renderHook(() => useWatchedPrints());
    act(() => void watchPrint({ kind: "item", printerId: P, jobIds: [A] }));
    act(() => event(A, "completed"));
    expect(result.current[0]!.phase).toBe("done");
  });

  it("keeps a failed job with its error code and does not drop it", () => {
    const { result } = renderHook(() => useWatchedPrints());
    act(() => void watchPrint({ kind: "test", printerId: P, jobIds: [A] }));
    act(() => event(A, "failed", { error_code: "printer-offline" }));
    expect(result.current[0]!.phase).toBe("failed");
    expect(result.current[0]!.failedJobIds).toEqual([A]);
    expect(result.current[0]!.live[A]?.errorCode).toBe("printer-offline");
  });

  it("shows batch progress as finished of total", () => {
    const { result } = renderHook(() => useWatchedPrints());
    act(() => void watchPrint({ kind: "cart", printerId: P, jobIds: [A, B, C] }));
    act(() => event(A, "done"));
    act(() => event(B, "printing"));
    const entry = result.current[0]!;
    expect(entry.total).toBe(3);
    expect(entry.finished).toBe(1);
    expect(entry.phase).toBe("printing");
    act(() => event(B, "done"));
    act(() => event(C, "failed"));
    expect(result.current[0]!.phase).toBe("failed");
    expect(result.current[0]!.finished).toBe(2);
  });

  it("gives several concurrent prints their own entries", () => {
    const { result } = renderHook(() => useWatchedPrints());
    act(() => void watchPrint({ kind: "item", printerId: P, jobIds: [A] }));
    act(() => void watchPrint({ kind: "item", printerId: P, jobIds: [B] }));
    act(() => event(B, "done"));
    expect(result.current.map((e) => e.phase)).toEqual(["queued", "done"]);
  });

  it("picks up an event that arrived before the print was registered", () => {
    act(() => event(A, "printing"));
    const { result } = renderHook(() => useWatchedPrints());
    act(() => void watchPrint({ kind: "item", printerId: P, jobIds: [A] }));
    expect(result.current[0]!.phase).toBe("printing");
  });

  it("reads the page-job sub-state", () => {
    const { result } = renderHook(() => useJobLive(A));
    act(() => event(A, "printing", { kind: "sheet_page", at_printer: "stopped", at_printer_reasons: ["toner-empty"], queue_depth: 2 }));
    expect(result.current).toMatchObject({ phase: "printing", atPrinter: "stopped", atPrinterReasons: ["toner-empty"] });
    // No position is exposed: the event's queue_depth counts the jobs behind this one as well.
    expect(result.current).not.toHaveProperty("queueDepth");
  });

  it("reads a paused job as paused, not as waiting normally", () => {
    const { result } = renderHook(() => useWatchedPrints());
    act(() => void watchPrint({ kind: "item", printerId: P, jobIds: [A] }));
    act(() => event(A, "paused"));
    expect(result.current[0]!.phase).toBe("paused");
  });

  it("does not rebuild the stack for a job nobody watches", () => {
    const { result } = renderHook(() => useWatchedPrints());
    act(() => void watchPrint({ kind: "item", printerId: P, jobIds: [A] }));
    const before = result.current;
    act(() => event(C, "printing"));
    expect(result.current).toBe(before);
    act(() => event(A, "printing"));
    expect(result.current).not.toBe(before);
  });

  it("a stale resync answer never overwrites a newer terminal frame", async () => {
    const { result } = renderHook(() => useWatchedPrints());
    act(() => void watchPrint({ kind: "item", printerId: P, jobIds: [A] }));
    let answer: (v: { state: string }) => void = () => {};
    const read = vi.fn(() => new Promise<{ state: string }>((resolve) => (answer = resolve)));
    let pending: Promise<void> = Promise.resolve();
    act(() => void (pending = resyncWatchedJobs(read)));
    // The done frame of the reopened stream arrives while the GET is out ...
    act(() => event(A, "completed"));
    // ... and the GET, sent earlier, answers `printing`.
    await act(async () => {
      answer({ state: "printing" });
      await pending;
    });
    expect(result.current[0]!.phase).toBe("done");
  });

  it("takes the error code of a failed job from the record's message when the frame never came", async () => {
    const { result } = renderHook(() => useWatchedPrints());
    act(() => void watchPrint({ kind: "item", printerId: P, jobIds: [A] }));
    await act(async () => void (await resyncWatchedJobs(async () => ({ state: "failed", error: "ipp_aborted: The printer aborted the job before printing." }))));
    expect(result.current[0]!.live[A]?.errorCode).toBe("ipp_aborted");
    expect(errorCodeFromMessage("Printer reported: cover open")).toBeNull();
  });

  it("dismisses an entry and swaps a retried job for the new one", () => {
    const { result } = renderHook(() => useWatchedPrints());
    let id = "";
    act(() => void (id = watchPrint({ kind: "item", printerId: P, jobIds: [A] })));
    act(() => event(A, "failed"));
    act(() => replaceWatchedJob(id, A, B));
    expect(result.current[0]!.phase).toBe("queued");
    expect(result.current[0]!.jobIds).toEqual([B]);
    act(() => dismissWatch(id));
    expect(result.current).toHaveLength(0);
  });

  it("resyncs after a reconnect: a job that ended while the stream was down is read again", async () => {
    const { result } = renderHook(() => useWatchedPrints());
    act(() => void watchPrint({ kind: "cart", printerId: P, jobIds: [A, B] }));
    act(() => event(B, "done"));
    const read = vi.fn(async (id: string) => ({ id, state: "done", error: null }));
    await act(async () => void (await resyncWatchedJobs(read)));
    // The finished job is not asked again; the open one is.
    expect(read).toHaveBeenCalledTimes(1);
    expect(read).toHaveBeenCalledWith(A);
    expect(result.current[0]!.phase).toBe("done");
  });

  it("keeps the old state when the resync read fails", async () => {
    const { result } = renderHook(() => useWatchedPrints());
    act(() => void watchPrint({ kind: "item", printerId: P, jobIds: [A] }));
    await act(async () => void (await resyncWatchedJobs(async () => Promise.reject(new Error("down")))));
    expect(result.current[0]!.phase).toBe("queued");
  });

  it("finds the entry that holds a job, also after a retry replaced it, and nothing once dismissed", () => {
    let id = "";
    act(() => void (id = watchPrint({ kind: "calibration", printerId: P, jobIds: [A] })));
    expect(watchedPrintOfJob(A)?.id).toBe(id);
    expect(watchedPrintOfJob(B)).toBeUndefined();
    act(() => replaceWatchedJob(id, A, B));
    expect(watchedPrintOfJob(A)).toBeUndefined();
    expect(watchedPrintOfJob(B)?.id).toBe(id);
    act(() => dismissWatch(id));
    expect(watchedPrintOfJob(B)).toBeUndefined();
  });

  it("a claimed job marks its card as claimed until the claim is released (once, however often released)", () => {
    const { result } = renderHook(() => useWatchedPrints());
    act(() => void watchPrint({ kind: "calibration", printerId: P, jobIds: [A] }));
    expect(result.current[0]!.claimed).toBe(false);
    let release = () => {};
    act(() => void (release = claimJob(A)));
    const releaseSecond = claimJob(A);
    expect(result.current[0]!.claimed).toBe(true);
    act(() => release());
    act(() => release());
    // Two lines claimed it; one released twice must not drop the other's claim.
    expect(result.current[0]!.claimed).toBe(true);
    act(() => releaseSecond());
    expect(result.current[0]!.claimed).toBe(false);
  });

  it("a print registered with claimPending is claimed until the line's claim arrives, and stays claimed with it", () => {
    const { result } = renderHook(() => useWatchedPrints());
    act(() => void watchPrint({ kind: "calibration", printerId: P, jobIds: [A], claimPending: true }));
    expect(result.current[0]!.claimed).toBe(true);
    let release = () => {};
    act(() => void (release = claimJob(A)));
    expect(result.current[0]!.claimed).toBe(true);
    // The line goes away: from here the stack announces the card like any other.
    act(() => release());
    expect(result.current[0]!.claimed).toBe(false);
  });

  it("releaseClaimPending clears a claim nobody will make", () => {
    const { result } = renderHook(() => useWatchedPrints());
    act(() => void watchPrint({ kind: "calibration", printerId: P, jobIds: [A], claimPending: true }));
    expect(result.current[0]!.claimed).toBe(true);
    act(() => releaseClaimPending(A));
    expect(result.current[0]!.claimed).toBe(false);
  });

  it("a retry hands the claim over to the new job: the card is claimed the whole time, and cannot stick", () => {
    const { result } = renderHook(() => useWatchedPrints());
    let id = "";
    act(() => void (id = watchPrint({ kind: "calibration", printerId: P, jobIds: [A] })));
    let release = () => {};
    act(() => void (release = claimJob(A)));
    act(() => replaceWatchedJob(id, A, B));
    // The new job is not claimed yet, the old claim still is: the card must not fall into the announced lists.
    expect(result.current[0]!.claimed).toBe(true);
    // The line follows: it releases the old claim and claims the new job in one go.
    let releaseNew = () => {};
    act(() => {
      release();
      releaseNew = claimJob(B);
    });
    expect(result.current[0]!.claimed).toBe(true);
    act(() => releaseNew());
    expect(result.current[0]!.claimed).toBe(false);
    // The line goes away before it followed: the old claim's release clears the hand-over.
    let id2 = "";
    act(() => void (id2 = watchPrint({ kind: "calibration", printerId: P, jobIds: [C] })));
    let releaseC = () => {};
    act(() => void (releaseC = claimJob(C)));
    act(() => replaceWatchedJob(id2, C, A));
    act(() => releaseC());
    expect(result.current.find((e) => e.id === id2)!.claimed).toBe(false);
  });

  it("a retry of a job nobody claims makes no claim pending", () => {
    const { result } = renderHook(() => useWatchedPrints());
    let id = "";
    act(() => void (id = watchPrint({ kind: "item", printerId: P, jobIds: [A] })));
    act(() => replaceWatchedJob(id, A, B));
    expect(result.current[0]!.claimed).toBe(false);
  });

  it("a reconnect resync also reads a job a page line shows after its card was dismissed", async () => {
    let id = "";
    act(() => void (id = watchPrint({ kind: "calibration", printerId: P, jobIds: [A] })));
    act(() => void claimJob(A));
    act(() => dismissWatch(id));
    const read = vi.fn(async () => ({ state: "done" }));
    const { result } = renderHook(() => useJobLive(A));
    await act(async () => void (await resyncWatchedJobs(read)));
    expect(read).toHaveBeenCalledWith(A);
    expect(result.current?.phase).toBe("done");
  });

  it("ignores events without a usable job id", () => {
    const { result } = renderHook(() => useWatchedPrints());
    act(() => void watchPrint({ kind: "item", printerId: P, jobIds: [A] }));
    act(() => recordJobEvent({ to_state: "done" }));
    expect(result.current[0]!.phase).toBe("queued");
  });
});

describe("a tape run in sub-jobs (#277)", () => {
  const ids = (n: number, from = 0) => Array.from({ length: n }, (_, i) => `00000000-0000-4000-8000-${String(from + i).padStart(12, "0")}`);
  const watchRun = (jobIds: string[]) => watchPrint({ kind: "cart", printerId: P, jobIds, run: { batchId: "batch-1", subJobStarts: [0, 3], confirmed: [] } });

  it("shows the sub-job that prints and, after it, waits for the user", () => {
    const { result } = renderHook(() => useWatchedPrints());
    const jobs = ids(5);
    act(() => void watchRun(jobs));
    act(() => event(jobs[0]!, "printing"));
    expect(result.current[0]!.run).toMatchObject({ subJob: 1, subJobs: 2, awaiting: false, unknownFrom: null });
    act(() => jobs.slice(0, 3).forEach((j) => event(j, "completed")));
    expect(result.current[0]!.run).toMatchObject({ subJob: 2, awaiting: true });
    expect(result.current[0]!.phase).toBe("printing");
    act(() => event(jobs[3]!, "printing"));
    expect(result.current[0]!.run).toMatchObject({ subJob: 2, awaiting: false });
  });

  it("after a stop names the unknown labels and counts nothing as failed that the user confirmed", () => {
    const { result } = renderHook(() => useWatchedPrints());
    const jobs = ids(5);
    let entryId = "";
    act(() => void (entryId = watchRun(jobs)));
    act(() => event(jobs[0]!, "completed"));
    act(() => jobs.slice(1, 3).forEach((j) => event(j, "failed", { error_code: "outcome_unknown" })));
    act(() => jobs.slice(3).forEach((j) => event(j, "failed", { error_code: "not_started" })));
    expect(result.current[0]!.phase).toBe("failed");
    expect(result.current[0]!.run).toMatchObject({ unknownFrom: 2, unknownTo: 3 });

    // Reprint from label 3: label 2 printed, 3..5 are new jobs.
    const fresh = ids(3, 100);
    act(() => replaceRunJobs(entryId, { jobIds: [...jobs.slice(0, 2), ...fresh], confirmed: [jobs[1]!], subJobStarts: [0, 2] }));
    const after = result.current[0]!;
    expect(after.failedJobIds).toEqual([]);
    expect(after.finished).toBe(2);
    expect(after.run).toMatchObject({ unknownFrom: null, subJob: 2 });
    act(() => fresh.forEach((j) => event(j, "completed")));
    expect(result.current[0]!.phase).toBe("done");
  });

  it("follows actions taken elsewhere by batch id: continue, reprint, discard, a run the hub forgot", () => {
    const { result } = renderHook(() => useWatchedPrints());
    const jobs = ids(5);
    act(() => void watchRun(jobs));
    act(() => jobs.slice(0, 3).forEach((j) => event(j, "completed")));
    act(() => runContinued("batch-1", 2));
    expect(result.current[0]!.run?.awaiting).toBe(false);
    act(() => runReprinted("batch-1", { jobIds: jobs.slice(0, 4), confirmed: [], subJobStarts: [0, 3] }));
    expect(result.current[0]!.total).toBe(4);
    act(() => forgetRun("batch-1"));
    expect(result.current[0]!.run).toBeUndefined();
    // A second print of the same batch id still has its run: a discard takes that card away.
    act(() => void watchRun(ids(2, 50)));
    act(() => runDiscarded("batch-1"));
    expect(result.current.map((e) => e.total)).toEqual([4]);
  });

  it("a run whose waiting labels a restart failed offers no actions any more", () => {
    const { result } = renderHook(() => useWatchedPrints());
    const jobs = ids(5);
    act(() => void watchRun(jobs));
    act(() => jobs.slice(0, 3).forEach((j) => event(j, "completed")));
    act(() => jobs.slice(3).forEach((j) => event(j, "failed", { error_code: "tape_run_interrupted" })));
    expect(result.current[0]!.run).toBeUndefined();
    expect(result.current[0]!.phase).toBe("failed");
  });

  describe("after a reconnect the code of the job record decides the run view", () => {
    it("a printing label the read reports as outcome_unknown is an unknown group, not a refusal", async () => {
      const { result } = renderHook(() => useWatchedPrints());
      const jobs = ids(5);
      act(() => void watchRun(jobs));
      act(() => jobs.slice(0, 3).forEach((j) => event(j, "completed")));
      act(() => jobs.slice(3).forEach((j) => event(j, "printing")));
      await act(async () => void (await resyncWatchedJobs(async () => ({ state: "failed_restart", error: "outcome_unknown: the link broke while sending" }))));
      expect(result.current[0]!.run).toMatchObject({ stopKind: "unknown", stopCode: "outcome_unknown", unknownFrom: 4, unknownTo: 5 });
    });

    it("a printing label the read reports as tape_run_interrupted takes the actions away", async () => {
      const { result } = renderHook(() => useWatchedPrints());
      const jobs = ids(5);
      act(() => void watchRun(jobs));
      act(() => jobs.slice(0, 3).forEach((j) => event(j, "completed")));
      act(() => jobs.slice(3).forEach((j) => event(j, "printing")));
      await act(async () => void (await resyncWatchedJobs(async () => ({ state: "failed_restart", error: "tape_run_interrupted: the hub restarted" }))));
      expect(result.current[0]!.run).toBeUndefined();
    });

    it("a refusal code of the read survives as the stop code", async () => {
      const { result } = renderHook(() => useWatchedPrints());
      const jobs = ids(5);
      act(() => void watchRun(jobs));
      act(() => jobs.slice(0, 3).forEach((j) => event(j, "completed")));
      act(() => jobs.slice(3).forEach((j) => event(j, "printing")));
      await act(async () => void (await resyncWatchedJobs(async () => ({ state: "failed", error: "ipp_aborted: The printer aborted the job." }))));
      expect(result.current[0]!.run).toMatchObject({ stopKind: "refused", stopCode: "ipp_aborted" });
    });
  });

  it("a continued sub-job does not offer the confirmation again while it waits for the worker", () => {
    const { result } = renderHook(() => useWatchedPrints());
    const jobs = ids(5);
    let entryId = "";
    act(() => void (entryId = watchRun(jobs)));
    act(() => jobs.slice(0, 3).forEach((j) => event(j, "completed")));
    expect(result.current[0]!.run?.awaiting).toBe(true);
    act(() => markRunContinued(entryId, 2));
    expect(result.current[0]!.run?.awaiting).toBe(false);
  });
});
