import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  dismissWatch,
  recordJobEvent,
  replaceWatchedJob,
  resetPrintWatch,
  resyncWatchedJobs,
  useJobLive,
  useWatchedPrints,
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

  it("reads the page-job sub-state and the jobs ahead", () => {
    const { result } = renderHook(() => useJobLive(A));
    act(() => event(A, "printing", { kind: "sheet_page", at_printer: "stopped", at_printer_reasons: ["toner-empty"], queue_depth: 2 }));
    expect(result.current).toMatchObject({ phase: "printing", atPrinter: "stopped", queueDepth: 2 });
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

  it("ignores events without a usable job id", () => {
    const { result } = renderHook(() => useWatchedPrints());
    act(() => void watchPrint({ kind: "item", printerId: P, jobIds: [A] }));
    act(() => recordJobEvent({ to_state: "done" }));
    expect(result.current[0]!.phase).toBe("queued");
  });
});
