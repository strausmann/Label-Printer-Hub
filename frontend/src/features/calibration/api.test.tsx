import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { calibrationOutOfRange, readingsInsufficient } from "../../api/errorDetail";
import { apiErrorBody, mockApi, PAGE_CAPABILITIES, PAGE_PRINTER, respond } from "../test-api";
import { calibrationPdfUrl, useCalibration, useCapabilities, useFit, usePrintCalibrationPage, useSaveCalibration } from "./api";

const P = PAGE_PRINTER.id;
function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client }, children);
  return { wrapper, invalidate: vi.spyOn(client, "invalidateQueries") };
}
afterEach(() => vi.unstubAllGlobals());

describe("calibration reads", () => {
  it("useCalibration lists the printer's calibrations", async () => {
    mockApi({ [`GET /api/printers/${P}/calibration`]: [{ tray: "main", offset_x_mm: 0.4 }] });
    const { wrapper } = setup();
    const { result } = renderHook(() => useCalibration(P), { wrapper });
    await waitFor(() => expect(result.current.data?.[0]?.tray).toBe("main"));
  });

  it("useCapabilities reads the printer's capabilities", async () => {
    mockApi({ [`GET /api/printers/${P}/capabilities`]: PAGE_CAPABILITIES });
    const { wrapper } = setup();
    const { result } = renderHook(() => useCapabilities(P), { wrapper });
    await waitFor(() => expect(result.current.data?.kind).toBe("page"));
  });
});

describe("calibration writes", () => {
  const values = { offset_x_mm: 0.4, offset_y_mm: -0.2, scale_x: 1, scale_y: 1, rotation_deg: 0 };

  it("useSaveCalibration puts the values for the tray and refreshes the calibrations", async () => {
    const { calls } = mockApi({ [`PUT /api/printers/${P}/calibration/main`]: { tray: "main", ...values } });
    const { wrapper, invalidate } = setup();
    const { result } = renderHook(() => useSaveCalibration(P), { wrapper });
    await act(() => result.current.mutateAsync({ tray: "main", values }));
    expect(JSON.parse(calls[0]!.body!)).toEqual(values);
    expect(invalidate.mock.calls.map((c) => c[0]?.queryKey)).toContainEqual(["printers", P, "calibration"]);
  });

  it("an out-of-range value surfaces the field and its range", async () => {
    mockApi({
      [`PUT /api/printers/${P}/calibration/main`]: () =>
        respond(422, apiErrorBody("calibration_out_of_range", "Out of range.", { field: "scale_x", min: 0.9, max: 1.1, reason: "too wide" })),
    });
    const { wrapper } = setup();
    const { result } = renderHook(() => useSaveCalibration(P), { wrapper });
    const error = await act(() => result.current.mutateAsync({ tray: "main", values }).catch((e: unknown) => e));
    expect(calibrationOutOfRange(error)).toMatchObject({ field: "scale_x", min: 0.9, max: 1.1 });
  });

  it("useFit posts the readings and returns the values", async () => {
    const { calls } = mockApi({ [`POST /api/printers/${P}/calibration/main/fit`]: { values: { ...values }, residuals_mm: [], flagged: [], out_of_range: [] } });
    const { wrapper } = setup();
    const { result } = renderHook(() => useFit(P), { wrapper });
    const answer = await act(() => result.current.mutateAsync({ tray: "main", request: { type: "L4736REV", readings: [] } }));
    expect(answer.values).toBeDefined();
    expect(calls[0]!.path).toBe(`/api/printers/${P}/calibration/main/fit`);
  });

  it("too few readings surface readings_insufficient", async () => {
    mockApi({ [`POST /api/printers/${P}/calibration/main/fit`]: () => respond(422, apiErrorBody("readings_insufficient", "Need 3.", { reason: "2 of 3" })) });
    const { wrapper } = setup();
    const { result } = renderHook(() => useFit(P), { wrapper });
    const error = await act(() => result.current.mutateAsync({ tray: "main", request: { type: "K", readings: [] } }).catch((e: unknown) => e));
    expect(readingsInsufficient(error)).toEqual({ reason: "2 of 3" });
  });

  it("usePrintCalibrationPage posts the page request and answers with the job", async () => {
    const { calls } = mockApi({ [`POST /api/printers/${P}/calibration/main/page`]: respond(202, { job_id: "j1" }) });
    const { wrapper } = setup();
    const { result } = renderHook(() => usePrintCalibrationPage(P), { wrapper });
    const answer = await act(() => result.current.mutateAsync({ tray: "main", request: { type: "L4736REV", corrected: true } }));
    expect(answer.job_id).toBe("j1");
    expect(JSON.parse(calls[0]!.body!)).toEqual({ type: "L4736REV", corrected: true });
  });
});

describe("calibrationPdfUrl", () => {
  it("ends in /page/pdf and carries the type, the version and the correction flag", () => {
    const url = calibrationPdfUrl(P, "main", { type: "L4736REV", version: 2, corrected: false });
    const [path, query] = url.split("?");
    expect(path).toBe(`/api/printers/${P}/calibration/main/page/pdf`);
    expect(path!.endsWith("/page/pdf")).toBe(true);
    expect(new URLSearchParams(query).toString()).toBe("type=L4736REV&version=2&corrected=false");
  });

  it("leaves the version out when none is named, and encodes the tray", () => {
    expect(calibrationPdfUrl(P, "by pass", { type: "K", corrected: true })).toBe(
      `/api/printers/${P}/calibration/by%20pass/page/pdf?type=K&corrected=true`,
    );
  });
});
