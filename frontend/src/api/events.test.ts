// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { QueryClient, QueryClientProvider, QueryObserver } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { emitSessionConfirmed, setOnUnauthorized, setSessionUnknown } from "./client";
import { resetPrintWatch, useWatchedPrints, watchPrint } from "../features/jobs/printWatch";
import { useHubEvents } from "./events";

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  url: string;
  withCredentials: boolean;
  closed = false;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  listeners = new Map<string, ((e: MessageEvent) => void)[]>();

  constructor(url: string, init?: { withCredentials?: boolean }) {
    this.url = url;
    this.withCredentials = init?.withCredentials ?? false;
    FakeEventSource.instances.push(this);
  }
  addEventListener(type: string, fn: (e: MessageEvent) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), fn]);
  }
  close() {
    this.closed = true;
  }
  open() {
    this.onopen?.();
  }
  fail() {
    this.onerror?.();
  }
  emit(type: string, printerId: string | null, data: unknown = {}) {
    const body = JSON.stringify({ channel: "hub", printer_id: printerId, type, ts: "2026-01-01T00:00:00Z", data });
    for (const fn of this.listeners.get(type) ?? []) fn(new MessageEvent(type, { data: body }));
  }
}

function hello(source: FakeEventSource, payload: unknown) {
  const listeners = (source as unknown as { listeners: Map<string, ((e: MessageEvent) => void)[]> }).listeners.get("hello") ?? [];
  for (const fn of listeners) fn(new MessageEvent("hello", { data: JSON.stringify(payload) }));
}

const last = () => FakeEventSource.instances[FakeEventSource.instances.length - 1]!;

function setup(client = new QueryClient()) {
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client }, children);
  const hook = renderHook(() => useHubEvents(), { wrapper });
  return { ...hook, invalidate, client };
}

const keys = (spy: ReturnType<typeof setup>["invalidate"]) => spy.mock.calls.map((c) => c[0]?.queryKey);

beforeEach(() => {
  resetPrintWatch();
  vi.useFakeTimers();
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
});

afterEach(() => {
  setOnUnauthorized(null);
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("useHubEvents", () => {
  it("opens one stream with cookies and reports connected", () => {
    const { result } = setup();
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(last().url).toBe("/api/v1/events");
    expect(last().withCredentials).toBe(true);
    expect(result.current.connected).toBe(false);
    act(() => last().open());
    expect(result.current.connected).toBe(true);
  });

  it("shows the new-version banner from the hello frame", async () => {
    const updates = await import("../app/updates");
    updates.setVersionCheckForTest({ buildVersion: "1.5.0" });
    const { result: banner } = renderHook(() => updates.useNeedRefresh());
    setup();
    expect(banner.current).toBe(false);
    act(() => hello(last(), { version: "1.6.0" }));
    expect(banner.current).toBe(true);
    updates.resetUpdatesForTest();
  });

  it("notices a new version after the hub was down for many retries, once it is back", async () => {
    const updates = await import("../app/updates");
    updates.setVersionCheckForTest({ buildVersion: "1.5.0" });
    const { result: banner } = renderHook(() => updates.useNeedRefresh());
    setup();
    act(() => last().open());
    // The hub restarts: the stream fails again and again (delays double up to the 30 s ceiling and stay there).
    for (let attempt = 0; attempt < 8; attempt++) {
      act(() => last().fail());
      act(() => void vi.advanceTimersByTime(31_000));
    }
    expect(FakeEventSource.instances.length).toBeGreaterThanOrEqual(9);
    expect(banner.current).toBe(false);
    // It is back, with the new version: the greeting after the reconnect raises the banner.
    act(() => last().open());
    act(() => hello(last(), { version: "1.6.0" }));
    expect(banner.current).toBe(true);
    updates.resetUpdatesForTest();
  });

  it("ignores a hello frame it cannot read", () => {
    setup();
    const fns = (last() as unknown as { listeners: Map<string, ((e: MessageEvent) => void)[]> }).listeners.get("hello") ?? [];
    expect(fns).toHaveLength(1);
    expect(() => fns[0]!(new MessageEvent("hello", { data: "not json" }))).not.toThrow();
  });

  it("job.state_changed invalidates jobs and the printer queue", () => {
    const { invalidate } = setup();
    act(() => last().emit("job.state_changed", "p1"));
    expect(keys(invalidate)).toEqual([["jobs"], ["printers", "p1", "queue"]]);
  });

  it("printer.status invalidates the printers prefix once, which reaches the printer's own queries", () => {
    const { invalidate } = setup();
    act(() => last().emit("printer.status", "p1"));
    expect(keys(invalidate)).toEqual([["printers"]]);
  });

  it("printer.tape_changed invalidates the printer", () => {
    const { invalidate } = setup();
    act(() => last().emit("printer.tape_changed", "p1"));
    expect(keys(invalidate)).toEqual([["printers", "p1"]]);
  });

  it("printer.roll_changed invalidates the status and the roll of the printer", () => {
    const { invalidate } = setup();
    act(() => last().emit("printer.roll_changed", "p1"));
    expect(keys(invalidate)).toEqual([
      ["printers", "p1", "status"],
      ["printers", "p1", "roll"],
    ]);
  });

  it("run.state_changed refreshes the held tape runs", () => {
    const { invalidate } = setup();
    act(() => last().emit("run.state_changed", "p1", { run_id: "r1", printer_id: "p1", state: "awaiting_confirmation" }));
    expect(keys(invalidate)).toEqual([["jobs", "held-runs"]]);
  });

  it("printer.identity_mismatch invalidates the printers prefix once, status included", () => {
    const { invalidate } = setup();
    act(() => last().emit("printer.identity_mismatch", "p1", { mismatch: true, since: "2026-11-09T10:00:00Z" }));
    expect(keys(invalidate)).toEqual([["printers"]]);
  });

  it("an event without a printer id only invalidates the lists", () => {
    const { invalidate } = setup();
    act(() => last().emit("job.state_changed", null));
    act(() => last().emit("printer.status", null));
    expect(keys(invalidate)).toEqual([["jobs"], ["printers"]]);
  });

  it("a frame that is not JSON still invalidates the list level", () => {
    const { invalidate } = setup();
    act(() => {
      for (const fn of (last() as unknown as { listeners: Map<string, ((e: MessageEvent) => void)[]> }).listeners.get(
        "printer.status",
      ) ?? [])
        fn(new MessageEvent("printer.status", { data: "not json" }));
    });
    expect(keys(invalidate)).toEqual([["printers"]]);
  });

  describe("sheet.updated", () => {
    const update = { code: "L4736-0001", free: 40, total: 48, changed: [3], state: "active" };

    it("invalidates the sheet lists, the sheet and previews", () => {
      const { invalidate } = setup();
      act(() => last().emit("sheet.updated", null, update));
      expect(keys(invalidate)).toEqual([["sheets", "list"], ["sheet-types"], ["sheets", "detail", "L4736-0001"], ["sheet-preview"]]);
    });

    it("only previews that name the code are invalidated", () => {
      const { invalidate } = setup();
      act(() => last().emit("sheet.updated", null, update));
      const predicate = invalidate.mock.calls[3]![0]!.predicate!;
      const preview = (request: unknown) => ({ queryKey: ["sheet-preview", "p1", request] }) as never;
      expect(predicate(preview({ items: [], placements: [{ sheet: "L4736-0001", cells: "first_free" }] }))).toBe(true);
      expect(predicate(preview({ items: [], placements: [{ sheet: "L4736-0002", cells: "first_free" }] }))).toBe(false);
      expect(predicate(preview({ items: [], placements: [{ sheet: "new", cells: "first_free" }] }))).toBe(false);
      expect(
        predicate(preview({ items: [], placements: [{ cells: "first_free" }], expected_cells: [{ sheet: "L4736-0001", cells: [1] }] })),
      ).toBe(true);
      expect(predicate({ queryKey: ["sheet-preview", "p1"] } as never)).toBe(false);
    });

    it("an update without a code still refreshes the lists", () => {
      const { invalidate } = setup();
      act(() => last().emit("sheet.updated", null, {}));
      expect(keys(invalidate)).toEqual([["sheets", "list"], ["sheet-types"]]);
    });

    it("refreshes the sheet-type list and detail, whose sheet counts move with every sheet", async () => {
      const { client } = setup();
      client.setQueryData(["sheet-types", "list", {}], []);
      client.setQueryData(["sheet-types", "detail", "L4736REV"], {});
      act(() => last().emit("sheet.updated", null, update));
      expect(client.getQueryState(["sheet-types", "list", {}])?.isInvalidated).toBe(true);
      expect(client.getQueryState(["sheet-types", "detail", "L4736REV"])?.isInvalidated).toBe(true);
    });
  });

  describe("page job sub-state", () => {
    const pageEvent = (at: string, over: Record<string, unknown> = {}) => ({
      job_id: "j1",
      from_state: "running",
      to_state: "running",
      kind: "sheet_page",
      at_printer: at,
      at_printer_reasons: [],
      summary: { sheet_code: "L4736-0001", cell_count: 3 },
      ...over,
    });

    it("keeps the latest sub-state per job", () => {
      const { client } = setup();
      act(() => last().emit("job.state_changed", "p1", pageEvent("waiting")));
      expect(client.getQueryData(["jobs", "j1", "at_printer"])).toEqual({
        kind: "sheet_page",
        atPrinter: "waiting",
        reasons: [],
        summary: { sheetCode: "L4736-0001", cellCount: 3 },
      });
      act(() => last().emit("job.state_changed", "p1", pageEvent("stopped", { at_printer_reasons: ["toner-empty"] })));
      expect(client.getQueryData(["jobs", "j1", "at_printer"])).toMatchObject({ atPrinter: "stopped", reasons: ["toner-empty"] });
    });

    it("keeps jobs apart and ignores jobs without a kind", () => {
      const { client } = setup();
      act(() => last().emit("job.state_changed", "p1", pageEvent("waiting")));
      act(() => last().emit("job.state_changed", "p1", pageEvent("printing", { job_id: "j2" })));
      act(() => last().emit("job.state_changed", "p1", { job_id: "j3", from_state: "queued", to_state: "running" }));
      expect(client.getQueryData(["jobs", "j1", "at_printer"])).toMatchObject({ atPrinter: "waiting" });
      expect(client.getQueryData(["jobs", "j2", "at_printer"])).toMatchObject({ atPrinter: "printing" });
      expect(client.getQueryData(["jobs", "j3", "at_printer"])).toBeUndefined();
    });

    it("an unreadable sub-state is stored as unknown, never guessed", () => {
      const { client } = setup();
      act(() => last().emit("job.state_changed", "p1", pageEvent("something-new", { at_printer_reasons: "x", summary: 5 })));
      expect(client.getQueryData(["jobs", "j1", "at_printer"])).toEqual({
        kind: "sheet_page",
        atPrinter: null,
        reasons: [],
        summary: null,
      });
    });
  });

  it("an event during a status query's first fetch is not lost: the status is read again after it lands", async () => {
    // The page printer's status producer sends a change once. If it arrives while the card's very
    // first status request is still out, that request's answer may be from before the change.
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    setup(client);
    const answers: ((v: string) => void)[] = [];
    const queryFn = vi.fn(() => new Promise<string>((resolve) => answers.push(resolve)));
    const observer = new QueryObserver(client, { queryKey: ["printers", "p1", "status"], queryFn });
    const unsubscribe = observer.subscribe(() => {});
    try {
      expect(queryFn).toHaveBeenCalledTimes(1);
      act(() => last().emit("printer.status", "p1"));
      await act(async () => answers[0]!("ready (read before the change)"));
      await act(async () => void (await vi.advanceTimersByTimeAsync(0)));
      expect(queryFn).toHaveBeenCalledTimes(2);
      await act(async () => answers[1]!("stopped"));
      expect(client.getQueryData(["printers", "p1", "status"])).toBe("stopped");
    } finally {
      unsubscribe();
    }
  });

  it("a query that already has data is refetched by the invalidation itself, not again after it lands", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    setup(client);
    client.setQueryData(["printers", "p1", "status"], "ready");
    const answers: ((v: string) => void)[] = [];
    const queryFn = vi.fn(() => new Promise<string>((resolve) => answers.push(resolve)));
    const observer = new QueryObserver(client, { queryKey: ["printers", "p1", "status"], queryFn, staleTime: 0 });
    const unsubscribe = observer.subscribe(() => {});
    try {
      // Data present: invalidation already cancels and restarts the fetch, so nothing more is needed.
      const before = queryFn.mock.calls.length;
      act(() => last().emit("printer.status", "p1"));
      await act(async () => void (await vi.advanceTimersByTimeAsync(0)));
      const afterEvent = queryFn.mock.calls.length;
      expect(afterEvent).toBeGreaterThan(before);
      await act(async () => answers[answers.length - 1]!("stopped"));
      await act(async () => void (await vi.advanceTimersByTimeAsync(0)));
      expect(queryFn).toHaveBeenCalledTimes(afterEvent);
      expect(client.getQueryData(["printers", "p1", "status"])).toBe("stopped");
    } finally {
      unsubscribe();
    }
  });

  describe("first loads that an event lands on, beyond the plain key paths", () => {
    const code = "L4736-0001";
    const previewKey = ["sheet-preview", "p1", { items: [], placements: [{ sheet: code, cells: "first_free" }] }];
    const client = () => new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const flush = () => act(async () => void (await vi.advanceTimersByTimeAsync(0)));

    function pendingQuery(c: QueryClient, queryKey: readonly unknown[]) {
      const answers: ((v: string) => void)[] = [];
      const rejections: ((e: Error) => void)[] = [];
      const queryFn = vi.fn(
        () =>
          new Promise<string>((resolve, reject) => {
            answers.push(resolve);
            rejections.push(reject);
          }),
      );
      const unsubscribe = new QueryObserver(c, { queryKey, queryFn }).subscribe(() => {});
      return { answers, rejections, queryFn, unsubscribe };
    }

    it("sheet.updated: a preview naming the code, still on its first render, is rendered again after it lands", async () => {
      const c = client();
      setup(c);
      const q = pendingQuery(c, previewKey);
      try {
        expect(q.queryFn).toHaveBeenCalledTimes(1);
        act(() => last().emit("sheet.updated", null, { code }));
        await act(async () => q.answers[0]!("render from before the update"));
        await flush();
        expect(q.queryFn).toHaveBeenCalledTimes(2);
      } finally {
        q.unsubscribe();
      }
    });

    it("sheet.updated: a preview that does not name the code is left alone", async () => {
      const c = client();
      setup(c);
      const q = pendingQuery(c, ["sheet-preview", "p1", { items: [], placements: [{ sheet: "L4736-0002", cells: "first_free" }] }]);
      try {
        act(() => last().emit("sheet.updated", null, { code }));
        await act(async () => q.answers[0]!("render"));
        await flush();
        expect(q.queryFn).toHaveBeenCalledTimes(1);
      } finally {
        q.unsubscribe();
      }
    });

    it("the resync after an automatic reconnect reads a preview again that is still on its first render", async () => {
      const c = client();
      setup(c);
      act(() => last().open());
      act(() => last().fail());
      act(() => void vi.advanceTimersByTime(1000));
      const q = pendingQuery(c, previewKey);
      try {
        act(() => last().open());
        await act(async () => q.answers[0]!("render from before the resync"));
        await flush();
        expect(q.queryFn).toHaveBeenCalledTimes(2);
      } finally {
        q.unsubscribe();
      }
    });

    it("a query in error, without data, is fetched once by the invalidation and not again after it lands", async () => {
      const c = client();
      setup(c);
      const q = pendingQuery(c, ["printers", "p1", "status"]);
      try {
        await act(async () => q.rejections[0]!(new Error("first fetch failed")));
        await flush();
        expect(c.getQueryState(["printers", "p1", "status"])?.status).toBe("error");
        act(() => last().emit("printer.status", "p1"));
        await flush();
        expect(q.queryFn).toHaveBeenCalledTimes(2);
        await act(async () => q.answers[1]!("ready"));
        await flush();
        expect(q.queryFn).toHaveBeenCalledTimes(2);
      } finally {
        q.unsubscribe();
      }
    });

    it("a second event before the restarted fetch of an errored query lands still gets its own follow-up", async () => {
      const c = client();
      setup(c);
      const q = pendingQuery(c, ["printers", "p1", "status"]);
      try {
        await act(async () => q.rejections[0]!(new Error("first fetch failed")));
        await flush();
        act(() => last().emit("printer.status", "p1")); // event A restarts the query: fetch 2
        await flush();
        expect(q.queryFn).toHaveBeenCalledTimes(2);
        act(() => last().emit("printer.status", "p1")); // event B joins fetch 2 (no data yet)
        await flush();
        expect(q.queryFn).toHaveBeenCalledTimes(2);
        await act(async () => q.answers[1]!("answer that may predate event B"));
        await flush();
        expect(q.queryFn).toHaveBeenCalledTimes(3);
      } finally {
        q.unsubscribe();
      }
    });

    it("a first fetch that fails is read again after the event too", async () => {
      const c = client();
      setup(c);
      const q = pendingQuery(c, ["printers", "p1", "status"]);
      try {
        act(() => last().emit("printer.status", "p1"));
        await act(async () => q.rejections[0]!(new Error("network down")));
        await flush();
        expect(q.queryFn).toHaveBeenCalledTimes(2);
      } finally {
        q.unsubscribe();
      }
    });
  });

  it("printers_changed invalidates printers and reopens the stream", () => {
    const { invalidate } = setup();
    const first = last();
    act(() => first.emit("hub.printers_changed", "p1", { printer_id: "p1", change: "added" }));
    expect(keys(invalidate)).toEqual([["printers"]]);
    expect(first.closed).toBe(true);
    expect(FakeEventSource.instances).toHaveLength(2);
    expect(last()).not.toBe(first);
  });

  it("auth.expired closes and signs out", () => {
    const handler = vi.fn();
    setOnUnauthorized(handler);
    setup();
    const es = last();
    act(() => es.emit("auth.expired", null));
    expect(es.closed).toBe(true);
    expect(handler).toHaveBeenCalledTimes(1);
    act(() => void vi.advanceTimersByTime(60_000));
    expect(FakeEventSource.instances).toHaveLength(1);
  });

  it("auth.expired reconnects after a backoff when the server still knows the session", async () => {
    // A restriction change or an SSO renewal ends the stream but not the session.
    setOnUnauthorized(() => Promise.resolve("valid"));
    setup();
    const es = last();
    await act(async () => es.emit("auth.expired", null));
    expect(es.closed).toBe(true);
    expect(FakeEventSource.instances).toHaveLength(1);
    act(() => void vi.advanceTimersByTime(1000));
    expect(FakeEventSource.instances).toHaveLength(2);
  });

  it("auth.expired without a definitive answer waits, then reconnects once the session is confirmed", async () => {
    setOnUnauthorized(() => Promise.resolve("unknown"));
    setup();
    await act(async () => last().emit("auth.expired", null));
    act(() => void vi.advanceTimersByTime(60_000));
    expect(FakeEventSource.instances).toHaveLength(1);
    act(() => emitSessionConfirmed());
    act(() => void vi.advanceTimersByTime(1000));
    expect(FakeEventSource.instances).toHaveLength(2);
  });

  it("auth.expired stays closed when the server says the session is gone", async () => {
    setOnUnauthorized(() => Promise.resolve("signed_out"));
    setup();
    await act(async () => last().emit("auth.expired", null));
    act(() => void vi.advanceTimersByTime(60_000));
    expect(FakeEventSource.instances).toHaveLength(1);
  });

  it("neither the error backoff nor the Reconnect button open a stream while the session is unverified", () => {
    const { result } = setup();
    act(() => last().open());
    setSessionUnknown(true);
    try {
      act(() => last().fail());
      act(() => void vi.advanceTimersByTime(60_000));
      expect(FakeEventSource.instances).toHaveLength(1);
      act(() => result.current.reconnect());
      expect(FakeEventSource.instances).toHaveLength(1);
      expect(result.current.connecting).toBe(false);
      setSessionUnknown(false);
      act(() => emitSessionConfirmed());
      act(() => void vi.advanceTimersByTime(30_000));
      expect(FakeEventSource.instances).toHaveLength(2);
    } finally {
      setSessionUnknown(false);
    }
  });

  it("reconnects after an error and resets the backoff once open", () => {
    const { result } = setup();
    act(() => last().open());
    act(() => last().fail());
    expect(result.current.connected).toBe(false);
    expect(FakeEventSource.instances).toHaveLength(1);
    act(() => void vi.advanceTimersByTime(999));
    expect(FakeEventSource.instances).toHaveLength(1);
    act(() => void vi.advanceTimersByTime(1));
    expect(FakeEventSource.instances).toHaveLength(2);
    act(() => last().open());
    expect(result.current.connected).toBe(true);
    act(() => last().fail());
    act(() => void vi.advanceTimersByTime(1000));
    expect(FakeEventSource.instances).toHaveLength(3);
  });

  it("after an automatic reconnect the sheet lists, the types and the previews are fetched again; the first open fetches nothing", () => {
    const { invalidate } = setup();
    act(() => last().open());
    expect(invalidate).not.toHaveBeenCalled();
    act(() => last().fail());
    act(() => void vi.advanceTimersByTime(1000));
    expect(invalidate).not.toHaveBeenCalled();
    act(() => last().open());
    expect(keys(invalidate)).toEqual([["sheets"], ["sheet-types"], ["sheet-preview"]]);
  });

  it("backoff doubles and caps at 30s", () => {
    setup();
    const delays = [1000, 2000, 4000, 8000, 16000, 30000, 30000];
    delays.forEach((delay, i) => {
      act(() => last().fail());
      const before = FakeEventSource.instances.length;
      expect(before).toBe(i + 1);
      act(() => void vi.advanceTimersByTime(delay - 1));
      expect(FakeEventSource.instances).toHaveLength(before);
      act(() => void vi.advanceTimersByTime(1));
      expect(FakeEventSource.instances).toHaveLength(before + 1);
    });
  });

  it("closes the stream and stops retrying on unmount", () => {
    const { unmount } = setup();
    const es = last();
    act(() => es.fail());
    unmount();
    act(() => void vi.advanceTimersByTime(60_000));
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(es.closed).toBe(true);
  });

  it("reconnect skips the pending backoff, reopens the stream and invalidates everything", () => {
    const { result, invalidate } = setup();
    for (let i = 0; i < 6; i++) {
      act(() => last().fail());
      act(() => void vi.advanceTimersByTime(30_000));
    }
    act(() => last().fail()); // next retry would wait 30 s
    const before = FakeEventSource.instances.length;
    act(() => result.current.reconnect());
    expect(FakeEventSource.instances).toHaveLength(before + 1);
    expect(invalidate).toHaveBeenCalledWith();
    // the cancelled timer does not open a second stream
    act(() => void vi.advanceTimersByTime(30_000));
    expect(FakeEventSource.instances).toHaveLength(before + 1);
    // backoff restarted at 1 s
    act(() => last().fail());
    act(() => void vi.advanceTimersByTime(1000));
    expect(FakeEventSource.instances).toHaveLength(before + 2);
  });

  it("is connecting from reconnect until the attempt opens or fails", () => {
    const { result } = setup();
    expect(result.current.connecting).toBe(false);
    act(() => result.current.reconnect());
    expect(result.current.connecting).toBe(true);
    act(() => last().fail());
    expect(result.current.connecting).toBe(false);
    act(() => result.current.reconnect());
    act(() => last().open());
    expect(result.current.connecting).toBe(false);
    expect(result.current.connected).toBe(true);
  });

  it("reconnect after auth.expired does nothing", () => {
    const { result } = setup();
    act(() => last().emit("auth.expired", null));
    act(() => result.current.reconnect());
    expect(FakeEventSource.instances).toHaveLength(1);
  });
});

describe("print watch feed", () => {
  const JOB = "aaaaaaaa-0000-4000-8000-000000000001";
  const watched = () => renderHook(() => useWatchedPrints());

  it("a job.state_changed frame moves the watched print, without a reload", () => {
    setup();
    const { result } = watched();
    act(() => void watchPrint({ kind: "item", printerId: "p1", jobIds: [JOB] }));
    act(() => last().emit("job.state_changed", "p1", { job_id: JOB, from_state: "queued", to_state: "printing" }));
    expect(result.current[0]!.phase).toBe("printing");
  });

  it("after an automatic reconnect an open watched job is read once; the first open reads nothing", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ id: JOB, state: "done", error: null }), { status: 200, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    setup();
    const { result } = watched();
    act(() => void watchPrint({ kind: "item", printerId: "p1", jobIds: [JOB] }));
    act(() => last().open());
    expect(fetchMock).not.toHaveBeenCalled();
    act(() => last().fail());
    act(() => void vi.advanceTimersByTime(1_000));
    await act(async () => last().open());
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String((fetchMock.mock.calls[0] as unknown[])[0])).toContain(`/api/v1/jobs/${JOB}`);
    expect(result.current[0]!.phase).toBe("done");
  });
});
