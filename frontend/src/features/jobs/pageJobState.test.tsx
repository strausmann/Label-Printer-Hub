import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { pageJobStateFrom, pageJobStateKey, usePageJobState } from "./pageJobState";

describe("pageJobStateFrom", () => {
  it("reads a page job event", () => {
    expect(
      pageJobStateFrom({ job_id: "j1", kind: "sheet_page", at_printer: "stopped", at_printer_reasons: ["media-empty"], summary: { sheet_code: "L4736-0001", cell_count: 9 } }),
    ).toEqual({ jobId: "j1", state: { kind: "sheet_page", atPrinter: "stopped", reasons: ["media-empty"], summary: { sheetCode: "L4736-0001", cellCount: 9 } } });
  });

  it.each([
    ["no kind", { job_id: "j1" }],
    ["no job id", { kind: "sheet_page" }],
    ["a job id that is not text", { job_id: 7, kind: "sheet_page" }],
  ])("is null for %s", (_name, data) => {
    expect(pageJobStateFrom(data)).toBeNull();
  });

  it("a summary that is not the server's {sheet_code, cell_count} is dropped, not guessed", () => {
    for (const summary of ["page 2 of 3", { sheet_code: "L4736-0001" }, { sheet_code: 4, cell_count: 1 }, null]) {
      expect(pageJobStateFrom({ job_id: "j1", kind: "k", summary })?.state.summary).toBeNull();
    }
  });

  it("an unknown place at the printer becomes null instead of a guess", () => {
    expect(pageJobStateFrom({ job_id: "j1", kind: "k", at_printer: "paper-jam" })?.state.atPrinter).toBeNull();
  });
});

describe("usePageJobState", () => {
  it("is undefined until an event stored something, then follows it, and never fetches", async () => {
    const client = new QueryClient();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const wrapper = ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client }, children);
    const { result } = renderHook(() => usePageJobState("j1"), { wrapper });
    expect(result.current).toBeUndefined();
    act(() => void client.setQueryData(pageJobStateKey("j1"), { kind: "k", atPrinter: "printing", reasons: [], summary: null }));
    await waitFor(() => expect(result.current?.atPrinter).toBe("printing"));
    // A job invalidation (every job event does one) must neither drop it nor fetch for it.
    await act(() => client.invalidateQueries({ queryKey: ["jobs"] }));
    expect(result.current?.atPrinter).toBe("printing");
    expect(fetchMock).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });
});
