import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { emitSessionConfirmed, setOnUnauthorized, setSessionUnknown } from "./client";
import { useHubEvents } from "./events";

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  url: string;
  withCredentials: boolean;
  closed = false;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  private listeners = new Map<string, ((e: MessageEvent) => void)[]>();

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

  it("job.state_changed invalidates jobs and the printer queue", () => {
    const { invalidate } = setup();
    act(() => last().emit("job.state_changed", "p1"));
    expect(keys(invalidate)).toEqual([["jobs"], ["printers", "p1", "queue"]]);
  });

  it("printer.status invalidates printers and the printer", () => {
    const { invalidate } = setup();
    act(() => last().emit("printer.status", "p1"));
    expect(keys(invalidate)).toEqual([["printers"], ["printers", "p1"]]);
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
