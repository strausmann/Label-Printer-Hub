import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  dismissWatch,
  errorCodeFromMessage,
  recordJobEvent,
  replaceWatchedJob,
  resetPrintWatch,
  resyncWatchedJobs,
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

  it("ignores events without a usable job id", () => {
    const { result } = renderHook(() => useWatchedPrints());
    act(() => void watchPrint({ kind: "item", printerId: P, jobIds: [A] }));
    act(() => recordJobEvent({ to_state: "done" }));
    expect(result.current[0]!.phase).toBe("queued");
  });
});
