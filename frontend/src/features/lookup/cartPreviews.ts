// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import type { CartItem } from "./cart";

/** How many different layouts the cart shows a preview of at most; the rest is counted, not drawn. */
export const MAX_CART_PREVIEWS = 4;

/** What the check route takes in one request. */
export const CHECK_CHUNK_SIZE = 50;

/** The cart's key for an item, also the key of its check result. */
export const itemKey = (item: Pick<CartItem, "app" | "id">): string => `${item.app}:${item.id}`;

/**
 * The first item of each content type, in cart order: a label looks alike for every item of one type, so one
 * preview per type tells what the batch will look like. `hiddenTypes` counts the types left out by the cap.
 */
export function distinctPreviews(items: CartItem[], max = MAX_CART_PREVIEWS): { shown: CartItem[]; hiddenTypes: number } {
  const firstOfType = new Map<string, CartItem>();
  for (const item of items) if (!firstOfType.has(item.content_type)) firstOfType.set(item.content_type, item);
  const all = [...firstOfType.values()];
  return { shown: all.slice(0, max), hiddenTypes: Math.max(0, all.length - max) };
}

/** The cart cut into requests the check route accepts. */
export function checkChunks(items: CartItem[], size = CHECK_CHUNK_SIZE): CartItem[][] {
  const chunks: CartItem[][] = [];
  for (let i = 0; i < items.length; i += size) chunks.push(items.slice(i, i + size));
  return chunks;
}
