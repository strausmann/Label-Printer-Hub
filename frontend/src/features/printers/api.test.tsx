// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi } from "../test-api";
import { useCancelJob, useClearQueue, usePauseResume, usePrinter, usePrinterStatus, useQueue, useResolveIdentity, useRoll, useSetRollColour, useTestPrint } from "./api";

const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{children}</QueryClientProvider>
);
const ID = "a/b?c#d";
const E = "a%2Fb%3Fc%23d";

afterEach(() => vi.unstubAllGlobals());

describe("printer route ids are encoded in the path", () => {
  it.each([
    ["printer", () => usePrinter(ID), `/api/v1/printers/${E}`],
    ["status", () => usePrinterStatus(ID), `/api/v1/printers/${E}/status`],
    ["queue", () => useQueue(ID), `/api/v1/printers/${E}/queue`],
    ["roll", () => useRoll(ID), `/api/v1/printers/${E}/roll`],
  ] as const)("%s", async (_name, hook, path) => {
    const { calls } = mockApi({ [`GET ${path}`]: {} });
    const { result } = renderHook(() => hook(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(calls.map((c) => c.path)).toEqual([path]);
  });

  it.each([
    ["pause", () => usePauseResume(), { id: ID, action: "pause" as const }, "POST", `/api/v1/printers/${E}/pause`],
    ["clear queue", () => useClearQueue(ID), undefined, "POST", `/api/v1/printers/${E}/queue/clear`],
    ["cancel job", () => useCancelJob("p"), ID, "POST", `/api/v1/jobs/${E}/cancel`],
    ["identity", () => useResolveIdentity(ID), { resolution: "same_device", expected_observed_id: "x", expected_observed_kind: "y" }, "POST", `/api/v1/admin/printers/${E}/identity/resolve`],
    ["roll colour", () => useSetRollColour(ID), { colour: null, width_mm: null, media_raw: null }, "PUT", `/api/v1/printers/${E}/roll`],
  ] as const)("%s", async (_name, hook, vars, method, path) => {
    const { calls } = mockApi({ [`${method} ${path}`]: {} });
    const { result } = renderHook(() => hook(), { wrapper });
    await (result.current.mutateAsync as (v: unknown) => Promise<unknown>)(vars);
    expect(calls[0]?.path).toBe(path);
  });

  it("test print encodes the printer id", async () => {
    const { calls } = mockApi({ [`POST /api/v1/printers/${E}/test-print`]: { job_id: "j" } });
    const { result } = renderHook(() => useTestPrint(ID), { wrapper });
    await result.current.mutateAsync(null);
    expect(calls[0]?.path).toBe(`/api/v1/printers/${E}/test-print`);
  });
});
