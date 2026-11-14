// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { calibrationOutOfRange, readingsInsufficient } from "../../api/errorDetail";
import { apiErrorBody, mockApi, PAGE_CAPABILITIES, PAGE_PRINTER, respond } from "../test-api";
import { calibrationPdfUrl, useCalibration, useCapabilities, useFit, usePrintCalibrationPage, useResetCalibration, useSaveCalibration } from "./api";

const P = PAGE_PRINTER.id;
function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client }, children);
  return { wrapper, invalidate: vi.spyOn(client, "invalidateQueries") };
}
afterEach(() => vi.unstubAllGlobals());

describe("calibration reads", () => {
  it("useCalibration lists the printer's calibrations", async () => {
    mockApi({ [`GET /api/v1/printers/${P}/calibration`]: [{ tray: "main", offset_x_mm: 0.4 }] });
    const { wrapper } = setup();
    const { result } = renderHook(() => useCalibration(P), { wrapper });
    await waitFor(() => expect(result.current.data?.[0]?.tray).toBe("main"));
  });

  it("useCapabilities reads the printer's capabilities", async () => {
    mockApi({ [`GET /api/v1/printers/${P}/capabilities`]: PAGE_CAPABILITIES });
    const { wrapper } = setup();
    const { result } = renderHook(() => useCapabilities(P), { wrapper });
    await waitFor(() => expect(result.current.data?.kind).toBe("page"));
  });
});

describe("calibration writes", () => {
  const values = { offset_x_mm: 0.4, offset_y_mm: -0.2, scale_x: 1, scale_y: 1, rotation_deg: 0 };

  it("useSaveCalibration puts the values for the tray and refreshes the calibrations", async () => {
    const { calls } = mockApi({ [`PUT /api/v1/printers/${P}/calibration/main`]: { tray: "main", ...values } });
    const { wrapper, invalidate } = setup();
    const { result } = renderHook(() => useSaveCalibration(P), { wrapper });
    await act(() => result.current.mutateAsync({ tray: "main", values }));
    expect(JSON.parse(calls[0]!.body!)).toEqual(values);
    const keys = invalidate.mock.calls.map((c) => c[0]?.queryKey);
    expect(keys).toContainEqual(["printers", P, "calibration"]);
    expect(keys).toContainEqual(["printers", P, "capabilities"]);
  });

  it("an out-of-range value surfaces the field and its range", async () => {
    mockApi({
      [`PUT /api/v1/printers/${P}/calibration/main`]: () =>
        respond(422, apiErrorBody("calibration_out_of_range", "Out of range.", { field: "scale_x", min: 0.9, max: 1.1, reason: "too wide" })),
    });
    const { wrapper } = setup();
    const { result } = renderHook(() => useSaveCalibration(P), { wrapper });
    const error = await act(() => result.current.mutateAsync({ tray: "main", values }).catch((e: unknown) => e));
    expect(calibrationOutOfRange(error)).toMatchObject({ field: "scale_x", min: 0.9, max: 1.1 });
  });

  it("useFit posts the readings and returns the values", async () => {
    const { calls } = mockApi({ [`POST /api/v1/printers/${P}/calibration/main/fit`]: { values: { ...values }, residuals_mm: [], flagged: [], out_of_range: [] } });
    const { wrapper } = setup();
    const { result } = renderHook(() => useFit(P), { wrapper });
    const answer = await act(() => result.current.mutateAsync({ tray: "main", request: { type: "L4736REV", readings: [] } }));
    expect(answer.values).toBeDefined();
    expect(calls[0]!.path).toBe(`/api/v1/printers/${P}/calibration/main/fit`);
  });

  it("too few readings surface readings_insufficient", async () => {
    mockApi({ [`POST /api/v1/printers/${P}/calibration/main/fit`]: () => respond(422, apiErrorBody("readings_insufficient", "Need 3.", { reason: "2 of 3" })) });
    const { wrapper } = setup();
    const { result } = renderHook(() => useFit(P), { wrapper });
    const error = await act(() => result.current.mutateAsync({ tray: "main", request: { type: "K", readings: [] } }).catch((e: unknown) => e));
    expect(readingsInsufficient(error)).toEqual({ reason: "2 of 3" });
  });

  it("usePrintCalibrationPage posts the page request and answers with the job", async () => {
    const { calls } = mockApi({ [`POST /api/v1/printers/${P}/calibration/main/page`]: respond(202, { job_id: "j1" }) });
    const { wrapper } = setup();
    const { result } = renderHook(() => usePrintCalibrationPage(P), { wrapper });
    const answer = await act(() => result.current.mutateAsync({ tray: "main", request: { type: "L4736REV", corrected: true } }));
    expect(answer.job_id).toBe("j1");
    expect(JSON.parse(calls[0]!.body!)).toEqual({ type: "L4736REV", corrected: true });
  });
});

describe("useResetCalibration", () => {
  const route = `DELETE /api/v1/printers/${P}/calibration/main`;

  it("deletes the tray's calibration and refreshes the calibrations and the capabilities", async () => {
    const { calls } = mockApi({ [route]: null });
    const { wrapper, invalidate } = setup();
    const { result } = renderHook(() => useResetCalibration(P), { wrapper });
    await act(() => result.current.mutateAsync({ tray: "main" }));
    expect(calls[0]).toMatchObject({ method: "DELETE", path: `/api/v1/printers/${P}/calibration/main` });
    const keys = invalidate.mock.calls.map((c) => c[0]?.queryKey);
    expect(keys).toContainEqual(["printers", P, "calibration"]);
    expect(keys).toContainEqual(["printers", P, "capabilities"]);
  });

  it("a backend error reaches the caller with its code, and the lists are refreshed anyway", async () => {
    mockApi({ [route]: () => respond(422, apiErrorBody("tray_unknown", "No such tray.")) });
    const { wrapper, invalidate } = setup();
    const { result } = renderHook(() => useResetCalibration(P), { wrapper });
    const error = (await act(() => result.current.mutateAsync({ tray: "main" }).catch((e: unknown) => e))) as { code?: string };
    expect(error.code).toBe("tray_unknown");
    expect(invalidate).toHaveBeenCalled();
  });

  it("a network error reaches the caller as status 0", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))));
    const { wrapper } = setup();
    const { result } = renderHook(() => useResetCalibration(P), { wrapper });
    const error = (await act(() => result.current.mutateAsync({ tray: "main" }).catch((e: unknown) => e))) as { status?: number };
    expect(error.status).toBe(0);
  });
});

describe("calibrationPdfUrl", () => {
  it("ends in /page/pdf and carries the type, the version and the correction flag", () => {
    const url = calibrationPdfUrl(P, "main", { type: "L4736REV", version: 2, corrected: false });
    const [path, query] = url.split("?");
    expect(path).toBe(`/api/v1/printers/${P}/calibration/main/page/pdf`);
    expect(path!.endsWith("/page/pdf")).toBe(true);
    expect(new URLSearchParams(query).toString()).toBe("type=L4736REV&version=2&corrected=false");
  });

  it("leaves the version out when none is named, and encodes the tray", () => {
    expect(calibrationPdfUrl(P, "by pass", { type: "K", corrected: true })).toBe(
      `/api/v1/printers/${P}/calibration/by%20pass/page/pdf?type=K&corrected=true`,
    );
  });
});
