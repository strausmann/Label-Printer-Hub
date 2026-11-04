import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setOnUnauthorized } from "./client";
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

function setup() {
  const client = new QueryClient();
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client }, children);
  const hook = renderHook(() => useHubEvents(), { wrapper });
  return { ...hook, invalidate };
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
