// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { focusManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, respond } from "../test-api";
import { PREVIEW_DEBOUNCE_MS } from "./api";
import type { CartItem } from "./cart";
import { useCartCheck } from "./useCartCheck";

const item = (n: number): CartItem => ({ app: "snipeit", id: String(n), name: `Item ${n}`, content_type: "qr_two_lines", copies: 1 });
const cart = (count: number, from = 1) => Array.from({ length: count }, (_, n) => item(from + n));

type Body = { items: { lookup: { identifier: string } }[] };
/** The check route as the server answers it: every item fine, in request order. */
const checkRoute = (extra: Record<string, unknown> = {}) => ({
  "POST /api/v1/render/check": (init: RequestInit) => ({
    results: (JSON.parse(String(init.body)) as Body).items.map((_, index) => ({ index, ok: true })),
  }),
  ...extra,
});
const sent = (calls: { path: string; body?: string }[]) =>
  calls.filter((c) => c.path === "/api/v1/render/check").map((c) => (JSON.parse(c.body!) as Body).items.map((i) => i.lookup.identifier));

function setup(initial: CartItem[]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  return renderHook(({ items }) => useCartCheck(items, 62, { orientation: "across", layout_preset: "compact" }), { wrapper, initialProps: { items: initial } });
}
const settle = () => act(() => new Promise((resolve) => setTimeout(resolve, PREVIEW_DEBOUNCE_MS + 80)));

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("useCartCheck", () => {
  it("removing an item sends nothing, adding one sends only that one", async () => {
    const { calls } = mockApi(checkRoute());
    const view = setup(cart(3));
    await waitFor(() => expect(view.result.current.flags.size).toBe(3));
    expect(sent(calls)).toEqual([["1", "2", "3"]]);

    view.rerender({ items: cart(2) });
    await settle();
    expect(sent(calls)).toHaveLength(1);
    expect(view.result.current.flags.size).toBe(2);

    view.rerender({ items: [...cart(2), item(9)] });
    await waitFor(() => expect(view.result.current.flags.size).toBe(3));
    expect(sent(calls)).toEqual([["1", "2", "3"], ["9"]]);
  });

  it("asks again for every item when the layout changes", async () => {
    const { calls } = mockApi(checkRoute());
    const client = new QueryClient();
    const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    const view = renderHook(({ preset }: { preset: "compact" | "standard" }) => useCartCheck(cart(2), 62, { orientation: "across", layout_preset: preset }), {
      wrapper,
      initialProps: { preset: "compact" },
    });
    await waitFor(() => expect(view.result.current.flags.size).toBe(2));
    view.rerender({ preset: "standard" });
    await waitFor(() => expect(sent(calls)).toHaveLength(2));
    expect(sent(calls)[1]).toEqual(["1", "2"]);
  });

  it("does not ask again when the window gets the focus after the verdicts went stale", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    const { calls } = mockApi(checkRoute());
    const view = setup(cart(2));
    await waitFor(() => expect(view.result.current.flags.size).toBe(2));
    vi.setSystemTime(Date.now() + 3_600_000);
    act(() => {
      focusManager.setFocused(false);
      focusManager.setFocused(true);
    });
    await settle();
    expect(sent(calls)).toHaveLength(1);
  });

  it("does not ask again on focus after a refused check", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    const { calls } = mockApi({ "POST /api/v1/render/check": respond(429, { detail: { error_code: "rate_limit_exceeded", error_message: "Slow down." } }) });
    const view = setup(cart(2));
    await waitFor(() => expect(view.result.current.isError).toBe(true));
    expect(view.result.current.flags.size).toBe(0);
    vi.setSystemTime(Date.now() + 3_600_000);
    act(() => {
      focusManager.setFocused(false);
      focusManager.setFocused(true);
    });
    await settle();
    expect(sent(calls)).toHaveLength(1);
  });

  it("stops sending chunks once the cart changed", async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => (release = resolve));
    let first = true;
    const { calls } = mockApi({
      "POST /api/v1/render/check": async (init: RequestInit) => {
        if (first) {
          first = false;
          await gate;
        }
        return { results: (JSON.parse(String(init.body)) as Body).items.map((_, index) => ({ index, ok: true })) };
      },
    });
    const view = setup(cart(120));
    await waitFor(() => expect(sent(calls)).toHaveLength(1));
    view.rerender({ items: cart(50) });
    await settle();
    release();
    await settle();
    // Chunk two and three of the old cart (items 51 to 120) were never sent.
    expect(sent(calls).flat().map(Number).filter((n) => n > 50)).toEqual([]);
  });
});
