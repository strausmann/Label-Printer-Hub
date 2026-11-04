import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useSyncExternalStore } from "react";
import { apiFetch } from "../../api/client";
import type { components } from "../../api/schema.gen";

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
function read(): CartItem[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(CART_KEY) ?? "[]");
    return Array.isArray(parsed) ? parsed.filter(isItem).map((i) => ({ ...i, copies: clampCopies(i.copies) })) : [];
  } catch {
    return [];
  }
}

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
  const existing = items.find((i) => sameItem(i, item));
  if (existing) {
    commit(items.map((i) => (i === existing ? { ...i, copies: clampCopies(i.copies + copies) } : i)));
  } else {
    commit([...items, { ...item, copies }]);
  }
}

const remove = (key: CartKey): void => commit(items.filter((i) => !sameItem(i, key)));
const clear = (): void => commit([]);
const setCopies = (key: CartKey, copies: number): void =>
  commit(items.map((i) => (sameItem(i, key) ? { ...i, copies: clampCopies(copies) } : i)));

/** The body item the batch endpoint takes: the server looks the item up again when it prints. */
export const toBatchItem = (item: CartItem) => ({
  content_type: item.content_type,
  options: { copies: item.copies },
  lookup: { app: item.app, identifier: item.id },
});

export function submitBatch(printerKey: string, list: CartItem[]): Promise<BatchResponse> {
  return apiFetch<BatchResponse>(`/api/print/${encodeURIComponent(printerKey)}/batch`, {
    method: "POST",
    json: { items: list.map(toBatchItem) },
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
  setCopies(key: CartKey, copies: number): void;
  clear(): void;
  /** Sends every item as ONE batch to the printer. The cart empties only once the server accepted it. */
  print(printerKey: string): Promise<BatchRead>;
}

export function useCart(): Cart {
  const current = useSyncExternalStore(subscribe, getSnapshot);
  const client = useQueryClient();
  const print = useCallback(
    async (printerKey: string): Promise<BatchRead> => {
      const sending = items;
      if (sending.length === 0) throw new Error("The cart is empty.");
      const accepted = await submitBatch(printerKey, sending);
      // Only now: a rejected batch leaves the cart as it was. Items added meanwhile stay.
      commit(items.filter((i) => !sending.some((s) => sameItem(s, i))));
      void client.invalidateQueries({ queryKey: ["jobs"] });
      try {
        return await apiFetch<BatchRead>(`/api/batches/${accepted.batch_id}`);
      } catch (error) {
        throw new BatchStatusError(accepted.batch_id, error);
      }
    },
    [client],
  );
  return { items: current, add, remove, setCopies, clear, print };
}
