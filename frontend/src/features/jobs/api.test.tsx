// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi } from "../test-api";
import { useCancelJobById, useContinueBatch, useDiscardBatch, useJob, useReprintBatch, useRetryJob } from "./api";

const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{children}</QueryClientProvider>
);
const ID = "a/b?c#d";
const ENCODED = "a%2Fb%3Fc%23d";

afterEach(() => vi.unstubAllGlobals());

describe("route ids are encoded in the path", () => {
  it("job ids are encoded in the path", async () => {
    const { calls } = mockApi({ [`GET /api/v1/jobs/${ENCODED}`]: { id: ID } });
    const { result } = renderHook(() => useJob("a/b?c#d"), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(calls.map((c) => c.path)).toEqual([`/api/v1/jobs/${ENCODED}`]);
    expect(calls[0]?.search).toBe("");
  });

  it.each([
    ["retry", () => useRetryJob(), `/api/v1/jobs/${ENCODED}/retry`],
    ["cancel", () => useCancelJobById(), `/api/v1/jobs/${ENCODED}/cancel`],
    ["continue", () => useContinueBatch(), `/api/v1/batches/${ENCODED}/continue`],
    ["discard", () => useDiscardBatch(), `/api/v1/batches/${ENCODED}/discard`],
  ] as const)("%s encodes the id", async (_name, hook, path) => {
    const { calls } = mockApi({ [`POST ${path}`]: {} });
    const { result } = renderHook(() => hook(), { wrapper });
    await result.current.mutateAsync(ID);
    expect(calls[0]?.path).toBe(path);
  });

  it("reprint encodes the batch id", async () => {
    const { calls } = mockApi({ [`POST /api/v1/batches/${ENCODED}/reprint`]: {} });
    const { result } = renderHook(() => useReprintBatch(), { wrapper });
    await result.current.mutateAsync({ batchId: ID, fromLabel: 3 });
    expect(calls[0]?.path).toBe(`/api/v1/batches/${ENCODED}/reprint`);
  });
});
