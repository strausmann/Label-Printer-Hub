// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { apiFetch } from "../../api/client";
import type { components } from "../../api/schema.gen";
import { useDebounced, type LayoutOptions } from "../layout/ql";
import { PREVIEW_DEBOUNCE_MS } from "./api";
import type { CartItem } from "./cart";
import { checkChunks, itemKey } from "./cartPreviews";

export type RenderCheckResult = components["schemas"]["RenderCheckResult"];
type RenderCheckResponse = components["schemas"]["RenderCheckResponse"];

/**
 * Asks the server which items of the cart it can draw for this tape and layout. The requests go one after the other:
 * the route charges the key's rate limit per distinct lookup, so parallel chunks would only race for the same budget.
 */
async function checkAll(items: CartItem[], tapeMm: number, layout: LayoutOptions | undefined): Promise<Map<string, RenderCheckResult>> {
  const flags = new Map<string, RenderCheckResult>();
  for (const chunk of checkChunks(items)) {
    const response = await apiFetch<RenderCheckResponse>("/api/v1/render/check", {
      method: "POST",
      json: {
        tape_mm: tapeMm,
        ...layout,
        items: chunk.map((i) => ({ content_type: i.content_type, lookup: { app: i.app, identifier: i.id } })),
      },
    });
    for (const result of response.results) {
      const item = chunk[result.index];
      if (item) flags.set(itemKey(item), result);
    }
  }
  return flags;
}

const NONE: ReadonlyMap<string, RenderCheckResult> = new Map();

/**
 * The verdict per cart item (key `app:id`). No check without a known tape. A failed check, a refused one (429) included,
 * is not tried again by itself: it answers `isError` and no flags, and the print checks the items anyway.
 */
export function useCartCheck(
  items: CartItem[],
  tapeMm: number | null,
  layout: LayoutOptions | undefined,
): { flags: ReadonlyMap<string, RenderCheckResult>; isPending: boolean; isError: boolean } {
  // A run of clicks (layout, copies, removing items) asks once.
  const wanted = JSON.stringify([tapeMm, layout ?? null, items.map((i) => [i.app, i.id, i.content_type])]);
  const settled = useDebounced(wanted, PREVIEW_DEBOUNCE_MS);
  const enabled = tapeMm !== null && items.length > 0 && settled === wanted;
  const query = useQuery({
    queryKey: ["render-check", settled],
    // Only runs once the debounce has caught up, so `items`, `tapeMm` and `layout` are what the key says.
    queryFn: () => checkAll(items, tapeMm as number, layout),
    enabled,
    retry: false,
    staleTime: 60_000,
    // The flags of the cart as it was stay while the new answer comes, so they do not flicker.
    placeholderData: keepPreviousData,
  });
  const active = tapeMm !== null && items.length > 0;
  return {
    flags: active && !query.isError ? (query.data ?? NONE) : NONE,
    isPending: active && query.isPending,
    isError: active && query.isError,
  };
}
