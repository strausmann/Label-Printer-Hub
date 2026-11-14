// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useSyncExternalStore } from "react";
import { apiFetch } from "../../api/client";
import type { components } from "../../api/schema.gen";
import { watchBatch } from "../jobs/printWatch";
import type { LayoutOptions } from "../layout/ql";

export type BatchRead = components["schemas"]["BatchRead"];
export type BatchResponse = components["schemas"]["BatchResponse"];
export type ContentType = components["schemas"]["ContentType"];
export type LookupApp = components["schemas"]["LookupResult"]["app"];

export interface CartItem {
  app: LookupApp;
  id: string;
  name: string;
  content_type: ContentType;
  copies: number;
}

/** Which entry of the cart: the same id can exist in two apps (Snipe-IT asset 7, Spoolman spool 7). */
export type CartKey = Pick<CartItem, "app" | "id">;

export const CART_KEY = "lph.cart";
export const MAX_COPIES = 10;

/** A line as a print took it: the key and the copies that were sent (labels, for a sheet print as well). */
export type SubmittedLine = CartKey & Pick<CartItem, "copies">;

const sameItem = (a: CartKey, b: CartKey) => a.app === b.app && a.id === b.id;
const clampCopies = (n: number) => Math.min(MAX_COPIES, Math.max(1, Math.round(Number.isFinite(n) ? n : 1)));

function isItem(value: unknown): value is CartItem {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    (v.app === "snipeit" || v.app === "grocy" || v.app === "spoolman") &&
    typeof v.id === "string" &&
    typeof v.name === "string" &&
    typeof v.content_type === "string" &&
    typeof v.copies === "number"
  );
}

/* The cart is a per-browser convenience: storage may be missing, full or hold junk. */
function readStored(): CartItem[] | null {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(CART_KEY) ?? "[]");
    return Array.isArray(parsed) ? parsed.filter(isItem).map((i) => ({ ...i, copies: clampCopies(i.copies) })) : null;
  } catch {
    return null;
  }
}
const read = (): CartItem[] => readStored() ?? [];

let items: CartItem[] = read();
const listeners = new Set<() => void>();

function commit(next: CartItem[]): void {
  items = next;
  try {
    localStorage.setItem(CART_KEY, JSON.stringify(next));
  } catch {
    /* keep the in-memory cart; it just will not survive a reload */
  }
  listeners.forEach((l) => l());
}

/**
 * The cart as it is stored right now. The in-memory copy only follows the asynchronous `storage` event, so
 * another tab may have written since. Unreadable or corrupt storage falls back to the in-memory cart.
 */
const current = (): CartItem[] => readStored() ?? items;

/** Every change of the cart goes through here: it starts from the stored cart, never from the possibly stale copy. */
function mutate(fn: (stored: CartItem[]) => CartItem[]): void {
  commit(fn(current()));
}

/** Takes the cart from storage again (another tab changed it; tests use it to simulate a fresh page). */
export function reloadCart(): void {
  items = read();
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  const onStorage = (event: StorageEvent) => {
    if (event.key === CART_KEY || event.key === null) reloadCart();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

const getSnapshot = () => items;

function add(item: CartItem): void {
  const copies = clampCopies(item.copies);
  mutate((stored) =>
    stored.some((i) => sameItem(i, item))
      ? stored.map((i) => (sameItem(i, item) ? { ...i, copies: clampCopies(i.copies + copies) } : i))
      : [...stored, { ...item, copies }],
  );
}

const remove = (key: CartKey): void => mutate((stored) => stored.filter((i) => !sameItem(i, key)));
/**
 * Takes out what was submitted, no more: a line another tab raised meanwhile keeps the copies that were never sent.
 * A line left with nothing (or less, when it was lowered meanwhile) goes; the rest is clamped like `setCopies`.
 */
const removeItems = (list: readonly SubmittedLine[]): void =>
  mutate((stored) =>
    stored.flatMap((i) => {
      const sent = list.filter((s) => sameItem(s, i)).reduce((sum, s) => sum + s.copies, 0);
      if (sent === 0) return [i];
      const left = i.copies - sent;
      return left <= 0 ? [] : [{ ...i, copies: clampCopies(left) }];
    }),
  );
/** Empties the cart whatever is stored: that is what the user asked for, so it needs no reconciling. */
const clear = (): void => commit([]);
const setCopies = (key: CartKey, copies: number): void =>
  mutate((stored) => stored.map((i) => (sameItem(i, key) ? { ...i, copies: clampCopies(copies) } : i)));

/** The body item the batch endpoint takes: the server looks the item up again when it prints. */
export const toBatchItem = (item: CartItem, layout?: LayoutOptions) => ({
  content_type: item.content_type,
  options: { copies: item.copies, ...layout },
  lookup: { app: item.app, identifier: item.id },
});

/** The chosen QL layout goes on every item: a batch prints in one direction. */
export function submitBatch(printerKey: string, list: CartItem[], layout?: LayoutOptions): Promise<BatchResponse> {
  return apiFetch<BatchResponse>(`/api/v1/print/${encodeURIComponent(printerKey)}/batch`, {
    method: "POST",
    json: { items: list.map((item) => toBatchItem(item, layout)) },
  });
}

/** The labels are queued but their status could not be read: the cart is already empty. */
export class BatchStatusError extends Error {
  readonly batchId: string;
  constructor(batchId: string, cause: unknown) {
    super("The batch was sent, but its status could not be read.", { cause });
    this.name = "BatchStatusError";
    this.batchId = batchId;
  }
}

export interface Cart {
  items: CartItem[];
  add(item: CartItem): void;
  remove(key: CartKey): void;
  /** Takes out the copies a print took; copies or lines added meanwhile stay. */
  removeItems(list: readonly SubmittedLine[]): void;
  setCopies(key: CartKey, copies: number): void;
  clear(): void;
  /** Sends every item as ONE batch to the printer. The cart empties only once the server accepted it. */
  print(printerKey: string, layout?: LayoutOptions): Promise<BatchRead>;
}

export function useCart(): Cart {
  const shown = useSyncExternalStore(subscribe, getSnapshot);
  const client = useQueryClient();
  const print = useCallback(
    async (printerKey: string, layout?: LayoutOptions): Promise<BatchRead> => {
      const sending = current();
      if (sending.length === 0) throw new Error("The cart is empty.");
      const accepted = await submitBatch(printerKey, sending, layout);
      // Only now: a rejected batch leaves the cart as it was. Items added meanwhile stay.
      removeItems(sending);
      watchBatch("cart", accepted);
      void client.invalidateQueries({ queryKey: ["jobs"] });
      try {
        return await apiFetch<BatchRead>(`/api/v1/batches/${accepted.batch_id}`);
      } catch (error) {
        throw new BatchStatusError(accepted.batch_id, error);
      }
    },
    [client],
  );
  return { items: shown, add, remove, removeItems, setCopies, clear, print };
}
