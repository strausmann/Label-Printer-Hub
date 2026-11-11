import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { prefixTaken, typeInUse } from "../../api/errorDetail";
import { apiErrorBody, mockApi, respond, SHEET_TYPE } from "../test-api";
import {
  exportTypeUrl,
  useAddVersion,
  useArchiveType,
  useCreateType,
  useDeleteType,
  useImportType,
  usePatchType,
  useSheetType,
  useSheetTypes,
} from "./api";

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client }, children);
  return { wrapper, invalidate: vi.spyOn(client, "invalidateQueries") };
}
afterEach(() => vi.unstubAllGlobals());

describe("sheet type reads", () => {
  it("useSheetTypes sends the set filters, drops an empty string and keeps true and decimals", async () => {
    const { calls } = mockApi({ "GET /api/v1/sheet-types": [SHEET_TYPE] });
    const { wrapper } = setup();
    const { result } = renderHook(() => useSheetTypes({ page: "A4", w: 45.7, h: 21.2, include_archived: true, vendor: "" }), { wrapper });
    await waitFor(() => expect(result.current.data).toHaveLength(1));
    expect(new URLSearchParams(calls[0]!.search).toString()).toBe("page=A4&w=45.7&h=21.2&include_archived=true");
  });

  it("useSheetType reads one type by key, encoded", async () => {
    const { calls } = mockApi({ "GET /api/v1/sheet-types/L4736REV": { ...SHEET_TYPE, versions: [] } });
    const { wrapper } = setup();
    const { result } = renderHook(() => useSheetType("L4736REV"), { wrapper });
    await waitFor(() => expect(result.current.data?.key).toBe("L4736REV"));
    expect(calls[0]!.path).toBe("/api/v1/sheet-types/L4736REV");
  });
});

describe("sheet type writes", () => {
  it("usePatchType patches the key and refreshes the type and the lists", async () => {
    const { calls } = mockApi({ "PATCH /api/v1/sheet-types/L4736REV": SHEET_TYPE });
    const { wrapper, invalidate } = setup();
    const { result } = renderHook(() => usePatchType(), { wrapper });
    await act(() => result.current.mutateAsync({ key: "L4736REV", patch: { description: "x" } }));
    expect(JSON.parse(calls[0]!.body!)).toEqual({ description: "x" });
    const keys = invalidate.mock.calls.map((c) => c[0]?.queryKey);
    expect(keys).toContainEqual(["sheet-types", "list"]);
    expect(keys).toContainEqual(["sheet-types", "detail", "L4736REV"]);
  });

  it("useCreateType surfaces prefix_taken with its reason", async () => {
    mockApi({ "POST /api/v1/sheet-types": () => respond(409, apiErrorBody("prefix_taken", "Taken.", { reason: "L47 belongs to L4736REV" })) });
    const { wrapper } = setup();
    const { result } = renderHook(() => useCreateType(), { wrapper });
    const error = await act(() => result.current.mutateAsync({} as never).catch((e: unknown) => e));
    expect(prefixTaken(error)).toEqual({ reason: "L47 belongs to L4736REV" });
  });

  it("useAddVersion posts to the versions address", async () => {
    const { calls } = mockApi({ "POST /api/v1/sheet-types/L4736REV/versions": respond(201, { version: 2 }) });
    const { wrapper } = setup();
    const { result } = renderHook(() => useAddVersion(), { wrapper });
    await act(() => result.current.mutateAsync({ key: "L4736REV", version: { change_note: "n" } as never }));
    expect(calls[0]!.path).toBe("/api/v1/sheet-types/L4736REV/versions");
  });

  it("useArchiveType archives, and unarchives on request", async () => {
    const { calls } = mockApi({ "POST /api/v1/sheet-types/L4736REV/archive": SHEET_TYPE, "POST /api/v1/sheet-types/L4736REV/unarchive": SHEET_TYPE });
    const { wrapper } = setup();
    const { result } = renderHook(() => useArchiveType(), { wrapper });
    await act(() => result.current.mutateAsync({ key: "L4736REV" }));
    await act(() => result.current.mutateAsync({ key: "L4736REV", unarchive: true }));
    expect(calls.map((c) => c.path)).toEqual(["/api/v1/sheet-types/L4736REV/archive", "/api/v1/sheet-types/L4736REV/unarchive"]);
  });

  it("useDeleteType deletes, and a type in use surfaces type_in_use", async () => {
    mockApi({ "DELETE /api/v1/sheet-types/L4736REV": () => respond(409, apiErrorBody("type_in_use", "In use.", { reason: "1 sheet" })) });
    const { wrapper } = setup();
    const { result } = renderHook(() => useDeleteType(), { wrapper });
    const error = await act(() => result.current.mutateAsync("L4736REV").catch((e: unknown) => e));
    expect(typeInUse(error)).toEqual({ reason: "1 sheet" });

    const ok = mockApi({ "DELETE /api/v1/sheet-types/L4736REV": null });
    await act(() => result.current.mutateAsync("L4736REV"));
    expect(ok.calls[0]!.method).toBe("DELETE");
  });

  it("useImportType sends the file as the body and the options as the query", async () => {
    const { calls } = mockApi({ "POST /api/v1/sheet-types/import": respond(201, { outcome: "created" }) });
    const { wrapper } = setup();
    const { result } = renderHook(() => useImportType(), { wrapper });
    await act(() => result.current.mutateAsync({ doc: { format: "x" } as never, options: { mode: "as_new_key", new_key: "K2", new_prefix: "K2" } }));
    expect(JSON.parse(calls[0]!.body!)).toEqual({ format: "x" });
    expect(new URLSearchParams(calls[0]!.search).toString()).toBe("mode=as_new_key&new_key=K2&new_prefix=K2");
  });
});

describe("import refreshes the type it touched", () => {
  it.each(["version_added", "unchanged", "created_as_new_key"])("%s invalidates the detail of the key in the answer", async (outcome) => {
    mockApi({ "POST /api/v1/sheet-types/import": respond(201, { outcome, key: "L4736REV-copy", version: 2 }) });
    const { wrapper, invalidate } = setup();
    const { result } = renderHook(() => useImportType(), { wrapper });
    await act(() => result.current.mutateAsync({ doc: { format: "x" } as never }));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["sheet-types", "detail", "L4736REV-copy"] });
  });

  it("a refused import names no type, so only the lists refresh", async () => {
    mockApi({ "POST /api/v1/sheet-types/import": respond(409, apiErrorBody("type_exists", "exists")) });
    const { wrapper, invalidate } = setup();
    const { result } = renderHook(() => useImportType(), { wrapper });
    await act(async () => {
      await result.current.mutateAsync({ doc: { format: "x" } as never }).catch(() => undefined);
    });
    expect(invalidate.mock.calls.some(([arg]) => (arg as { queryKey: string[] }).queryKey[1] === "detail")).toBe(false);
  });
});

describe("exportTypeUrl", () => {
  it("is the export address, with the version when one is named", () => {
    expect(exportTypeUrl("L4736REV")).toBe("/api/v1/sheet-types/L4736REV/export");
    expect(exportTypeUrl("L4736REV", 2)).toBe("/api/v1/sheet-types/L4736REV/export?version=2");
    expect(exportTypeUrl("A/B C", 0)).toBe("/api/v1/sheet-types/A%2FB%20C/export?version=0");
  });
});
