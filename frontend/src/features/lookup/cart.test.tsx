// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import { mockApi, respond } from "../test-api";
import { CART_KEY, reloadCart, useCart, type CartItem } from "./cart";

const BATCH_ID = "cccccccc-0000-4000-8000-000000000001";
const PRINTER = "11111111-1111-4111-8111-111111111111";
const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>
);

const asset: CartItem = { app: "snipeit", id: "42", name: "Drill", content_type: "qr_two_lines", copies: 1 };
const spool: CartItem = { app: "spoolman", id: "7", name: "PLA red", content_type: "qr_one_line", copies: 2 };

beforeEach(() => {
  localStorage.clear();
  reloadCart();
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetModules();
});

function batchRoutes(over: Record<string, unknown> = {}) {
  return {
    [`POST /api/v1/print/${PRINTER}/batch`]: { batch_id: BATCH_ID, printer_id: PRINTER, queued_at: "2026-11-04T10:00:00Z", job_ids: ["j1", "j2"] },
    [`GET /api/v1/batches/${BATCH_ID}`]: { id: BATCH_ID, printer_id: PRINTER, created_by: null, created_at: "2026-11-04T10:00:00Z", jobs: [], summary: { total: 2, queued: 2, printing: 0, done: 0, failed: 0, cancelled: 0, all_terminal: false } },
    ...over,
  };
}

describe("cart", () => {
  it("survives reload", async () => {
    const first = renderHook(() => useCart(), { wrapper });
    act(() => first.result.current.add(asset));
    act(() => first.result.current.add(spool));
    first.unmount();

    // A reload starts a fresh module: only localStorage is left.
    vi.resetModules();
    const fresh = await import("./cart");
    const second = renderHook(() => fresh.useCart(), { wrapper });
    expect(second.result.current.items).toEqual([asset, spool]);
  });

  it("adding the same item again raises its copies instead of listing it twice", () => {
    const { result } = renderHook(() => useCart(), { wrapper });
    act(() => result.current.add(asset));
    act(() => result.current.add(asset));
    expect(result.current.items).toEqual([{ ...asset, copies: 2 }]);
  });

  it("the same id in two apps is two items, and remove takes only the one asked for", () => {
    const { result } = renderHook(() => useCart(), { wrapper });
    act(() => result.current.add({ ...asset, id: "7" }));
    act(() => result.current.add(spool));
    act(() => result.current.remove({ app: "spoolman", id: "7" }));
    expect(result.current.items.map((i) => i.app)).toEqual(["snipeit"]);
  });

  it("works without storage (private mode) and ignores a corrupt entry", () => {
    localStorage.setItem(CART_KEY, "{not json");
    const { result } = renderHook(() => useCart(), { wrapper });
    expect(result.current.items).toEqual([]);
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });
    act(() => result.current.add(asset));
    expect(result.current.items).toHaveLength(1);
    vi.restoreAllMocks();
  });

  it("removeItems drops the entries by key and leaves the others", () => {
    const { result } = renderHook(() => useCart(), { wrapper });
    act(() => result.current.add(asset));
    act(() => result.current.add(spool));
    act(() => result.current.add({ ...spool, app: "snipeit" }));
    act(() => result.current.removeItems([spool]));
    expect(result.current.items.map((i) => `${i.app}:${i.id}`)).toEqual(["snipeit:42", `snipeit:${spool.id}`]);
    expect(JSON.parse(localStorage.getItem(CART_KEY)!)).toHaveLength(2);
  });

  describe("another tab wrote and this tab has not heard of it yet (no storage event, no reloadCart)", () => {
    const other: CartItem = { app: "grocy", id: "99", name: "Rice", content_type: "qr_one_line", copies: 1 };
    const otherTab = (...list: CartItem[]) => localStorage.setItem(CART_KEY, JSON.stringify(list));
    const stored = () => (JSON.parse(localStorage.getItem(CART_KEY)!) as CartItem[]).map((i) => `${i.app}:${i.id}:${i.copies}`);

    it("removeItems of a submitted line keeps the other tab's new line", () => {
      const { result } = renderHook(() => useCart(), { wrapper });
      act(() => result.current.add(asset));
      otherTab(asset, other);
      act(() => result.current.removeItems([asset]));
      expect(stored()).toEqual(["grocy:99:1"]);
      expect(result.current.items.map((i) => i.id)).toEqual(["99"]);
    });

    it("removeItems keeps the copies another tab added after the line was submitted", () => {
      const { result } = renderHook(() => useCart(), { wrapper });
      act(() => result.current.add({ ...asset, copies: 2 }));
      otherTab({ ...asset, copies: 3 });
      act(() => result.current.removeItems([{ ...asset, copies: 2 }]));
      expect(stored()).toEqual(["snipeit:42:1"]);
      expect(result.current.items.map((i) => i.copies)).toEqual([1]);
    });

    it("removeItems removes a line that is unchanged since the submit", () => {
      const { result } = renderHook(() => useCart(), { wrapper });
      act(() => result.current.add({ ...asset, copies: 2 }));
      act(() => result.current.removeItems([{ ...asset, copies: 2 }]));
      expect(stored()).toEqual([]);
    });

    it("removeItems removes a line that was lowered below the submitted count and never goes negative", () => {
      const { result } = renderHook(() => useCart(), { wrapper });
      act(() => result.current.add({ ...asset, copies: 3 }));
      otherTab({ ...asset, copies: 1 }, other);
      act(() => result.current.removeItems([{ ...asset, copies: 3 }]));
      expect(stored()).toEqual(["grocy:99:1"]);
    });

    it("print keeps the copies another tab added while the request was in flight", async () => {
      mockApi(batchRoutes());
      const { result } = renderHook(() => useCart(), { wrapper });
      act(() => result.current.add({ ...asset, copies: 2 }));
      await act(async () => {
        const printing = result.current.print(PRINTER);
        otherTab({ ...asset, copies: 3 });
        await printing;
      });
      expect(stored()).toEqual(["snipeit:42:1"]);
    });

    it("add keeps the other tab's new line", () => {
      const { result } = renderHook(() => useCart(), { wrapper });
      act(() => result.current.add(asset));
      otherTab(asset, other);
      act(() => result.current.add(spool));
      expect(stored()).toEqual(["snipeit:42:1", "grocy:99:1", "spoolman:7:2"]);
    });

    it("setCopies keeps the other tab's new line", () => {
      const { result } = renderHook(() => useCart(), { wrapper });
      act(() => result.current.add(asset));
      otherTab(asset, other);
      act(() => result.current.setCopies(asset, 5));
      expect(stored()).toEqual(["snipeit:42:5", "grocy:99:1"]);
    });

    it("remove keeps the other tab's new line", () => {
      const { result } = renderHook(() => useCart(), { wrapper });
      act(() => result.current.add(asset));
      otherTab(asset, other);
      act(() => result.current.remove(asset));
      expect(stored()).toEqual(["grocy:99:1"]);
    });

    it("print keeps a line another tab wrote while the request was in flight", async () => {
      mockApi(batchRoutes());
      const { result } = renderHook(() => useCart(), { wrapper });
      act(() => result.current.add(asset));
      await act(async () => {
        const printing = result.current.print(PRINTER);
        otherTab(asset, other);
        await printing;
      });
      expect(stored()).toEqual(["grocy:99:1"]);
    });
  });

  it("print sends one batch with all items and clears on success", async () => {
    const { calls } = mockApi(batchRoutes());
    const { result } = renderHook(() => useCart(), { wrapper });
    act(() => result.current.add(asset));
    act(() => result.current.add(spool));

    let batch: Awaited<ReturnType<typeof result.current.print>> | undefined;
    await act(async () => {
      batch = await result.current.print(PRINTER);
    });

    const posts = calls.filter((c) => c.method === "POST");
    expect(posts).toHaveLength(1);
    expect(JSON.parse(posts[0]!.body!)).toEqual({
      items: [
        { content_type: "qr_two_lines", options: { copies: 1 }, lookup: { app: "snipeit", identifier: "42" } },
        { content_type: "qr_one_line", options: { copies: 2 }, lookup: { app: "spoolman", identifier: "7" } },
      ],
    });
    expect(posts[0]!.headers.get("X-CSRF-Token")).toBeDefined();
    expect(batch?.id).toBe(BATCH_ID);
    expect(result.current.items).toEqual([]);
    expect(localStorage.getItem(CART_KEY)).toBe("[]");
  });

  it("keeps items when the batch is rejected", async () => {
    mockApi(batchRoutes({ [`POST /api/v1/print/${PRINTER}/batch`]: respond(409, { detail: { error_code: "printer_offline", error_message: "Printer is offline" } }) }));
    const { result } = renderHook(() => useCart(), { wrapper });
    act(() => result.current.add(asset));
    act(() => result.current.add(spool));

    let error: unknown;
    await act(async () => {
      error = await result.current.print(PRINTER).catch((e: unknown) => e);
    });

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe("printer_offline");
    expect(result.current.items).toEqual([asset, spool]);
    expect(JSON.parse(localStorage.getItem(CART_KEY)!)).toHaveLength(2);
  });

  it("printing an empty cart sends nothing", async () => {
    const { calls } = mockApi(batchRoutes());
    const { result } = renderHook(() => useCart(), { wrapper });
    await expect(result.current.print(PRINTER)).rejects.toThrow();
    await waitFor(() => expect(calls).toHaveLength(0));
  });

  it("clears the cart even when only the batch status cannot be read afterwards", async () => {
    mockApi(batchRoutes({ [`GET /api/v1/batches/${BATCH_ID}`]: respond(500, { detail: "boom" }) }));
    const { result } = renderHook(() => useCart(), { wrapper });
    act(() => result.current.add(asset));
    let error: unknown;
    await act(async () => {
      error = await result.current.print(PRINTER).catch((e: unknown) => e);
    });
    // The labels are queued: the cart must not offer to print them a second time.
    expect(result.current.items).toEqual([]);
    expect((error as { batchId?: string }).batchId).toBe(BATCH_ID);
  });
});
