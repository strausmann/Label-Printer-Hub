// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import { cellsTaken, insufficientCells, planChanged, printInterrupted } from "../../api/errorDetail";
import { apiErrorBody, mockApi, PAGE_PRINTER, PRINTED_PAGE, respond, sheetPreview, sheetRead, sheetSummary } from "../test-api";
import {
  calibrationKey,
  capabilitiesKey,
  sheetKey,
  sheetPreviewKey,
  sheetsKey,
  useCreateSheet,
  useDiscardSheet,
  useMarginCheck,
  useMarkCells,
  useNextCode,
  usePrintSheets,
  useResolveAllCells,
  useResolveCells,
  useSheet,
  useSheetPreview,
  useSheets,
  useUnmarkCells,
} from "./api";

import { resetPrintWatch, useWatchedPrints } from "../jobs/printWatch";

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client }, children);
  return { client, wrapper, invalidate: vi.spyOn(client, "invalidateQueries") };
}

afterEach(() => vi.unstubAllGlobals());

describe("query keys", () => {
  it("previews sit outside the printers tree, capabilities and calibration inside it", () => {
    expect(sheetPreviewKey("p1", { items: [], placements: [] })[0]).not.toBe("printers");
    expect(capabilitiesKey("p1").slice(0, 2)).toEqual(["printers", "p1"]);
    expect(calibrationKey("p1").slice(0, 2)).toEqual(["printers", "p1"]);
  });

  it("lists and details share the prefixes the event hook invalidates", () => {
    expect(sheetsKey({ state: "all" }).slice(0, 2)).toEqual(["sheets", "list"]);
    expect(sheetKey("L4736-0001")).toEqual(["sheets", "detail", "L4736-0001"]);
  });
});

describe("reads", () => {
  it("useSheets sends the set filters only", async () => {
    const { calls } = mockApi({ "GET /api/v1/sheets": [sheetSummary()] });
    const { wrapper } = setup();
    const { result } = renderHook(() => useSheets({ type: "L4736REV", free_at_least: 3, state: "active", q: "" }), { wrapper });
    await waitFor(() => expect(result.current.data).toHaveLength(1));
    expect(new URLSearchParams(calls[0]!.search).toString()).toBe("type=L4736REV&free_at_least=3&state=active");
  });

  it("useSheets without filters sends no query string", async () => {
    const { calls } = mockApi({ "GET /api/v1/sheets": [] });
    const { wrapper } = setup();
    renderHook(() => useSheets(), { wrapper });
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]!.search).toBe("");
  });

  it("useSheet reads one sheet by code", async () => {
    mockApi({ "GET /api/v1/sheets/L4736-0001": sheetRead() });
    const { wrapper } = setup();
    const { result } = renderHook(() => useSheet("L4736-0001"), { wrapper });
    await waitFor(() => expect(result.current.data?.code).toBe("L4736-0001"));
  });

  it("useSheet does not ask for an empty code", () => {
    const { calls } = mockApi({});
    const { wrapper } = setup();
    renderHook(() => useSheet(""), { wrapper });
    expect(calls).toHaveLength(0);
  });

  it("useNextCode waits for a type, then asks for it", async () => {
    const { calls } = mockApi({ "GET /api/v1/sheets/next-code": { code: "L4736-0002", hint: "probable" } });
    const { wrapper } = setup();
    const { result, rerender } = renderHook(({ type }: { type: string | null }) => useNextCode(type), {
      wrapper,
      initialProps: { type: null as string | null },
    });
    expect(calls).toHaveLength(0);
    rerender({ type: "L4736REV" });
    await waitFor(() => expect(result.current.data?.code).toBe("L4736-0002"));
    expect(calls[0]!.search).toBe("?type=L4736REV");
  });

  it("useMarginCheck sends type, printer and the tray when one is chosen", async () => {
    const { calls } = mockApi({
      "GET /api/v1/sheets/margin-check": { band: "top", printable: true, qr: true, reason: null, bands_mm: { top: 9, bottom: 5, left: 5, right: 5 }, corner: null, feed_mark: true, usable_mm: 9 },
    });
    const { wrapper } = setup();
    const { result } = renderHook(() => useMarginCheck("L4736REV", PAGE_PRINTER.id, "bypass"), { wrapper });
    await waitFor(() => expect(result.current.data?.band).toBe("top"));
    expect(new URLSearchParams(calls[0]!.search).get("tray")).toBe("bypass");
    expect(new URLSearchParams(calls[0]!.search).get("printer")).toBe(PAGE_PRINTER.id);
  });
});

describe("sheet writes", () => {
  it("useCreateSheet posts the request, refreshes the lists and surfaces insufficient_cells with its data", async () => {
    const { calls } = mockApi({
      "POST /api/v1/sheets": () =>
        respond(409, apiErrorBody("insufficient_cells", "Not enough free cells.", { free_cells: [1, 2], needed: 5, shortfall: 3 })),
    });
    const { wrapper, invalidate } = setup();
    const { result } = renderHook(() => useCreateSheet(), { wrapper });
    const error = await act(() =>
      result.current.mutateAsync({ type: "L4736REV", used_cells: [], id_placement: "cell" }).catch((e: unknown) => e),
    );
    expect(JSON.parse(calls[0]!.body!)).toEqual({ type: "L4736REV", used_cells: [], id_placement: "cell" });
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe("insufficient_cells");
    expect(insufficientCells(error)).toEqual({ capacity: [1, 2], needed: 5, shortfall: 3 });
    expect(invalidate.mock.calls.map((c) => c[0]?.queryKey)).toContainEqual(["sheets", "list"]);
  });

  it("useDiscardSheet puts the discarded sheet into the cache", async () => {
    mockApi({ "POST /api/v1/sheets/L4736-0001/discard": sheetRead("L4736-0001", { used: [1] }, { state: "discarded", discarded_at: "2026-11-05T08:00:00Z" }) });
    const { wrapper, client } = setup();
    const { result } = renderHook(() => useDiscardSheet(), { wrapper });
    await act(() => result.current.mutateAsync("L4736-0001"));
    expect(client.getQueryData<{ state: string }>(sheetKey("L4736-0001"))?.state).toBe("discarded");
  });

  it("a write that answers with the sheet does not refetch that sheet", async () => {
    const { calls } = mockApi({
      "GET /api/v1/sheets/L4736-0001": sheetRead(),
      "POST /api/v1/sheets/L4736-0001/cells/mark": sheetRead("L4736-0001", { used: [1, 7] }),
      "POST /api/v1/sheets/L4736-0001/discard": sheetRead("L4736-0001", {}, { state: "discarded" }),
    });
    const { wrapper, client } = setup();
    const detail = renderHook(() => useSheet("L4736-0001"), { wrapper });
    await waitFor(() => expect(detail.result.current.data).toBeDefined());
    const mark = renderHook(() => useMarkCells(), { wrapper });
    const discard = renderHook(() => useDiscardSheet(), { wrapper });
    await act(() => mark.result.current.mutateAsync({ code: "L4736-0001", cells: [{ cell: 7 }] }));
    await act(() => discard.result.current.mutateAsync("L4736-0001"));
    await act(() => client.invalidateQueries({ queryKey: ["nothing"] }));
    expect(calls.filter((c) => c.method === "GET" && c.path === "/api/v1/sheets/L4736-0001")).toHaveLength(1);
  });

  it("mark, unmark and resolve post the cells to their own address and cache the answer", async () => {
    const { calls } = mockApi({
      "POST /api/v1/sheets/L4736-0001/cells/mark": sheetRead("L4736-0001", { used: [1, 7] }),
      "POST /api/v1/sheets/L4736-0001/cells/unmark": sheetRead("L4736-0001", { used: [1] }),
      "POST /api/v1/sheets/L4736-0001/cells/resolve": sheetRead("L4736-0001", { used: [1, 8] }),
    });
    const { wrapper, client } = setup();
    const mark = renderHook(() => useMarkCells(), { wrapper });
    const unmark = renderHook(() => useUnmarkCells(), { wrapper });
    const resolve = renderHook(() => useResolveCells(), { wrapper });

    await act(() => mark.result.current.mutateAsync({ code: "L4736-0001", cells: [{ cell: 7, purpose: "spare" }] }));
    expect(client.getQueryData<{ used: number }>(sheetKey("L4736-0001"))?.used).toBe(2);
    await act(() => unmark.result.current.mutateAsync({ code: "L4736-0001", cells: [7] }));
    expect(client.getQueryData<{ used: number }>(sheetKey("L4736-0001"))?.used).toBe(1);
    await act(() => resolve.result.current.mutateAsync({ code: "L4736-0001", cells: [8], outcome: "printed" }));

    expect(calls.map((c) => [c.path, JSON.parse(c.body!)])).toEqual([
      ["/api/v1/sheets/L4736-0001/cells/mark", { cells: [{ cell: 7, purpose: "spare" }] }],
      ["/api/v1/sheets/L4736-0001/cells/unmark", { cells: [7] }],
      ["/api/v1/sheets/L4736-0001/cells/resolve", { cells: [8], outcome: "printed" }],
    ]);
  });

  it("useResolveAllCells posts the outcome and the expected count and caches the sheet", async () => {
    const { calls } = mockApi({ "POST /api/v1/sheets/AB-12/cells/resolve-all": sheetRead("AB-12", { used: [1, 2] }) });
    const { wrapper, client } = setup();
    const { result } = renderHook(() => useResolveAllCells(), { wrapper });
    await act(() => result.current.mutateAsync({ code: "AB-12", outcome: "not_printed", expectedCount: 2 }));
    expect(calls.map((c) => [c.path, JSON.parse(c.body!)])).toEqual([["/api/v1/sheets/AB-12/cells/resolve-all", { outcome: "not_printed", expected_count: 2 }]]);
    expect(client.getQueryData<{ code: string }>(sheetKey("AB-12"))?.code).toBe("AB-12");
  });

  it("useResolveAllCells surfaces a network error as isError", async () => {
    mockApi({
      "POST /api/v1/sheets/AB-12/cells/resolve-all": () => {
        throw new TypeError("Failed to fetch");
      },
    });
    const { wrapper } = setup();
    const { result } = renderHook(() => useResolveAllCells(), { wrapper });
    await act(() => result.current.mutateAsync({ code: "AB-12", outcome: "printed", expectedCount: 2 }).catch(() => undefined));
    await waitFor(() => expect(result.current.isError).toBe(true));
  });

  it("a cell write that fails keeps the cached sheet and surfaces the code", async () => {
    mockApi({ "POST /api/v1/sheets/L4736-0001/cells/mark": () => respond(409, apiErrorBody("cells_taken", "Taken.", { cells: [7] })) });
    const { wrapper, client } = setup();
    client.setQueryData(sheetKey("L4736-0001"), sheetRead());
    const { result } = renderHook(() => useMarkCells(), { wrapper });
    const error = await act(() => result.current.mutateAsync({ code: "L4736-0001", cells: [{ cell: 7 }] }).catch((e: unknown) => e));
    expect(cellsTaken(error)).toEqual({ cells: [7] });
    expect(client.getQueryData<{ used: number }>(sheetKey("L4736-0001"))?.used).toBe(3);
  });
});

describe("preview and print", () => {
  const request = { items: [], placements: [{ sheet: "L4736-0001", cells: "first_free" as const }] };

  it("useSheetPreview posts the request to the printer's preview address", async () => {
    const { calls } = mockApi({ [`POST /api/v1/print/${PAGE_PRINTER.id}/sheet/preview`]: sheetPreview() });
    const { wrapper } = setup();
    const { result } = renderHook(() => useSheetPreview(PAGE_PRINTER.id, request), { wrapper });
    await waitFor(() => expect(result.current.data?.pages).toHaveLength(1));
    expect(JSON.parse(calls[0]!.body!)).toEqual(request);
  });

  it("useSheetPreview does not ask while disabled and does not retry plan_changed", async () => {
    const { calls } = mockApi({
      [`POST /api/v1/print/${PAGE_PRINTER.id}/sheet/preview`]: () => respond(409, apiErrorBody("plan_changed", "Changed.", { plan: [{ sheet: "L4736-0001", cells: [4], id_cell: null }] })),
    });
    const { wrapper } = setup();
    renderHook(() => useSheetPreview(PAGE_PRINTER.id, request, false), { wrapper });
    expect(calls).toHaveLength(0);
    const on = renderHook(() => useSheetPreview(PAGE_PRINTER.id, request), { wrapper });
    await waitFor(() => expect(on.result.current.isError).toBe(true));
    expect(planChanged(on.result.current.error)).toEqual({ plan: [{ sheet: "L4736-0001", cells: [4], id_cell: null }] });
    expect(calls).toHaveLength(1);
  });

  it("usePrintSheets answers with the batch and refreshes sheets, previews and jobs", async () => {
    mockApi({ [`POST /api/v1/print/${PAGE_PRINTER.id}/sheet`]: respond(202, { batch_id: "b1", pages: [PRINTED_PAGE] }) });
    const { wrapper, invalidate } = setup();
    const { result } = renderHook(() => usePrintSheets(PAGE_PRINTER.id), { wrapper });
    const answer = await act(() => result.current.mutateAsync(request));
    expect(answer.batch_id).toBe("b1");
    const keys = invalidate.mock.calls.map((c) => c[0]?.queryKey);
    expect(keys).toContainEqual(["sheets", "list"]);
    expect(keys).toContainEqual(["sheet-preview"]);
    expect(keys).toContainEqual(["jobs"]);
  });

  it("a partly printed batch surfaces print_interrupted and still refreshes", async () => {
    mockApi({
      [`POST /api/v1/print/${PAGE_PRINTER.id}/sheet`]: () =>
        respond(502, apiErrorBody("print_interrupted", "Interrupted.", { batch_id: "b1", job_ids: ["j1"] })),
    });
    const { wrapper, invalidate } = setup();
    const { result } = renderHook(() => usePrintSheets(PAGE_PRINTER.id), { wrapper });
    const error = await act(() => result.current.mutateAsync(request).catch((e: unknown) => e));
    expect(printInterrupted(error)).toEqual({ batchId: "b1", jobIds: ["j1"] });
    expect(invalidate.mock.calls.map((c) => c[0]?.queryKey)).toContainEqual(["jobs"]);
  });

  it("the pages of a partly printed batch get a print status entry, a plain failure does not", async () => {
    resetPrintWatch();
    mockApi({
      [`POST /api/v1/print/${PAGE_PRINTER.id}/sheet`]: () =>
        respond(502, apiErrorBody("print_interrupted", "Interrupted.", { batch_id: "b1", job_ids: ["j1", "j2"] })),
    });
    const { wrapper } = setup();
    const { result } = renderHook(() => usePrintSheets(PAGE_PRINTER.id), { wrapper });
    await act(() => result.current.mutateAsync(request).catch(() => undefined));
    const watched = renderHook(() => useWatchedPrints());
    expect(watched.result.current).toMatchObject([{ kind: "sheet", printerId: PAGE_PRINTER.id, jobIds: ["j1", "j2"] }]);
    resetPrintWatch();
    mockApi({ [`POST /api/v1/print/${PAGE_PRINTER.id}/sheet`]: () => respond(422, { detail: "no" }) });
    await act(() => result.current.mutateAsync(request).catch(() => undefined));
    expect(renderHook(() => useWatchedPrints()).result.current).toHaveLength(0);
  });
});
