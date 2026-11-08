import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useDebounced } from "./useDebounced";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("useDebounced", () => {
  it("starts with the value at once, follows a change only after the wait, and says so meanwhile", () => {
    const { result, rerender } = renderHook(({ v }) => useDebounced(v, 400), { initialProps: { v: { n: 1 } } });
    expect(result.current).toEqual({ value: { n: 1 }, pending: false });
    rerender({ v: { n: 2 } });
    expect(result.current).toEqual({ value: { n: 1 }, pending: true });
    act(() => void vi.advanceTimersByTime(399));
    expect(result.current.value).toEqual({ n: 1 });
    act(() => void vi.advanceTimersByTime(1));
    expect(result.current).toEqual({ value: { n: 2 }, pending: false });
  });

  it("a change inside the wait restarts it, and an equal object does not", () => {
    const { result, rerender } = renderHook(({ v }) => useDebounced(v, 400), { initialProps: { v: { n: 1 } } });
    rerender({ v: { n: 2 } });
    act(() => void vi.advanceTimersByTime(300));
    rerender({ v: { n: 3 } });
    act(() => void vi.advanceTimersByTime(300));
    expect(result.current.value).toEqual({ n: 1 });
    act(() => void vi.advanceTimersByTime(100));
    expect(result.current.value).toEqual({ n: 3 });
    rerender({ v: { n: 3 } });
    expect(result.current.pending).toBe(false);
  });
});
