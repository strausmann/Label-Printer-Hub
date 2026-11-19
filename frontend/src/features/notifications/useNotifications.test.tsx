// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { noteServerVersion, resetUpdatesForTest, setVersionCheckForTest, startUpdates } from "../../app/updates";
import { job, mockApi, PRINTER_A, status } from "../test-api";
import { useAttention, useNotifications } from "./useNotifications";

afterEach(() => resetUpdatesForTest());

const J1 = "aaaaaaaa-0000-4000-8000-000000000001";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function setup() {
  setVersionCheckForTest({ buildVersion: "1.5.0", reload: vi.fn() });
  mockApi({
    "GET /api/v1/printers": [PRINTER_A],
    [`GET /api/v1/printers/${PRINTER_A.id}/status`]: status(PRINTER_A.id),
    // A failed job: the one entry "Needs attention" must list.
    "GET /api/v1/jobs": [job(J1, PRINTER_A.id, "failed", { updated_at: new Date().toISOString() })],
  });
}

describe("useNotifications: a new version (#354)", () => {
  it("the feed carries the update entry", async () => {
    setup();
    const { result } = renderHook(() => useNotifications(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(result.current.entries.some((e) => e.kind === "update")).toBe(false);
    act(() => noteServerVersion("1.6.0"));
    const update = result.current.entries.find((e) => e.kind === "update");
    expect(update).toMatchObject({ id: "update:1.6.0", severity: "warning", action: "reload", values: { version: "1.6.0" } });
    expect(result.current.visible).toContainEqual(update);
    act(() => noteServerVersion("1.5.0"));
    expect(result.current.entries.some((e) => e.kind === "update")).toBe(false);
  });

  it("Needs attention never lists the update", async () => {
    setup();
    const { result } = renderHook(() => useAttention(), { wrapper });
    act(() => noteServerVersion("1.6.0"));
    await waitFor(() => expect(result.current.entries.some((e) => e.textKey === "job.failed")).toBe(true));
    expect(result.current.entries.some((e) => e.kind === "update")).toBe(false);
  });

  it("the entry keeps its id when the versions match while a worker waits", async () => {
    setup();
    let needRefresh!: () => void;
    startUpdates((options) => {
      needRefresh = options.onNeedRefresh;
      return async () => {};
    });
    const { result } = renderHook(() => useNotifications(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("ready"));
    act(() => noteServerVersion("1.6.0"));
    act(() => needRefresh());
    act(() => noteServerVersion("1.5.0"));
    expect(result.current.entries.filter((e) => e.kind === "update").map((e) => e.id)).toEqual(["update:1.6.0"]);
  });
});

