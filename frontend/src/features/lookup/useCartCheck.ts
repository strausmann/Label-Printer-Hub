// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { apiFetch } from "../../api/client";
import type { components } from "../../api/schema.gen";
import { useDebounced, type LayoutOptions } from "../layout/ql";
import { PREVIEW_DEBOUNCE_MS } from "./api";
import type { CartItem } from "./cart";
import { checkChunks, itemKey } from "./cartPreviews";

export type RenderCheckResult = components["schemas"]["RenderCheckResult"];
type RenderCheckResponse = components["schemas"]["RenderCheckResponse"];

/**
 * Asks the server which items it can draw for this tape and layout. The requests go one after the other: the route
 * charges the key's rate limit per distinct lookup, so parallel chunks would only race for the same budget. Every
 * answer is handed to `keep` as it arrives, so an interrupted run loses only the chunk in flight.
 */
async function checkAll(
  items: CartItem[],
  tapeMm: number,
  layout: LayoutOptions | undefined,
  keep: (item: CartItem, result: RenderCheckResult) => void,
  signal: AbortSignal,
): Promise<void> {
  for (const chunk of checkChunks(items)) {
    // The inputs changed while an earlier chunk was on its way: the next request would be for a cart that is gone.
    if (signal.aborted) throw new DOMException("The cart changed.", "AbortError");
    const response = await apiFetch<RenderCheckResponse>("/api/v1/render/check", {
      method: "POST",
      signal,
      json: {
        tape_mm: tapeMm,
        ...layout,
        items: chunk.map((i) => ({ content_type: i.content_type, lookup: { app: i.app, identifier: i.id } })),
      },
    });
    for (const result of response.results) {
      const item = chunk[result.index];
      if (item) keep(item, result);
    }
  }
}

const NONE: ReadonlyMap<string, RenderCheckResult> = new Map();

/**
 * The verdict per cart item (key `app:id`). No check without a known tape.
 *
 * A verdict is kept per item, tape and layout. Only the items without one are sent: removing an item costs no
 * request, adding one costs one lookup, so a cart edited a few times does not burn the key's rate limit. A verdict
 * never goes stale by itself (no refetch on focus or reconnect): the cart is local, and the print checks every item
 * again. A failed check, a refused one (429) included, is not tried again by itself: it answers `isError` and no flags.
 */
export function useCartCheck(
  items: CartItem[],
  tapeMm: number | null,
  layout: LayoutOptions | undefined,
): { flags: ReadonlyMap<string, RenderCheckResult>; isPending: boolean; isError: boolean } {
  // Mutated as answers arrive, never replaced: a render reads what the finished requests left.
  const [kept] = useState(() => new Map<string, RenderCheckResult>());
  const layoutKey = JSON.stringify(layout ?? null);
  const verdictKey = (item: CartItem) => `${tapeMm}|${layoutKey}|${item.app}:${item.id}:${item.content_type}`;
  // A run of clicks (layout, copies, removing items) asks once.
  const wanted = JSON.stringify([tapeMm, layoutKey, items.map((i) => [i.app, i.id, i.content_type])]);
  const settled = useDebounced(wanted, PREVIEW_DEBOUNCE_MS);
  const active = tapeMm !== null && items.length > 0;
  const missing = active ? items.filter((i) => !kept.has(verdictKey(i))) : [];
  const query = useQuery({
    queryKey: ["render-check", tapeMm, layoutKey, missing.map((i) => [i.app, i.id, i.content_type])],
    // Only runs once the debounce has caught up, so `missing`, `tapeMm` and `layout` are what the key says.
    queryFn: async ({ signal }) => {
      await checkAll(missing, tapeMm as number, layout, (item, result) => kept.set(verdictKey(item), result), signal);
      return true;
    },
    enabled: missing.length > 0 && settled === wanted,
    retry: false,
    // Nothing makes a verdict stale: the key holds every input that matters.
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
  // Reading `status` is what re-renders on success: the verdicts live in `kept`, which React Query knows nothing about.
  const failed = query.status === "error";
  const flags = new Map<string, RenderCheckResult>();
  if (active && !(failed && missing.length > 0)) {
    for (const item of items) {
      const verdict = kept.get(verdictKey(item));
      if (verdict) flags.set(itemKey(item), verdict);
    }
  }
  return {
    flags: flags.size > 0 ? flags : NONE,
    isPending: missing.length > 0 && !failed,
    isError: missing.length > 0 && failed,
  };
}
