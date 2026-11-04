import { useSyncExternalStore } from "react";
import type { LookupApp } from "./cart";

export type RecentKind = "asset" | "location" | "product" | "spool";

/** Nothing here is a secret: an id, the name the lookup showed, what it is, when. */
export interface RecentItem {
  id: string;
  name: string;
  kind: RecentKind;
  at: number;
}

export const RECENT_LIMIT = 10;
export const recentKey = (app: LookupApp) => `lph.recent.${app}`;

const KINDS: readonly RecentKind[] = ["asset", "location", "product", "spool"];

export function kindOf(app: LookupApp, id: string): RecentKind {
  if (app === "grocy") return "product";
  if (app === "spoolman") return "spool";
  return id.startsWith("loc:") ? "location" : "asset";
}

function isItem(value: unknown): value is RecentItem {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return typeof v.id === "string" && typeof v.name === "string" && typeof v.at === "number" && KINDS.includes(v.kind as RecentKind);
}

/* Per-browser convenience: storage may be missing, full or hold junk. */
function read(app: LookupApp): RecentItem[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(recentKey(app)) ?? "[]");
    return Array.isArray(parsed) ? parsed.filter(isItem).slice(0, RECENT_LIMIT) : [];
  } catch {
    return [];
  }
}

const lists = new Map<LookupApp, RecentItem[]>();
const listeners = new Set<() => void>();
const current = (app: LookupApp): RecentItem[] => {
  let list = lists.get(app);
  if (!list) {
    list = read(app);
    lists.set(app, list);
  }
  return list;
};

/** Takes every list from storage again (another tab changed it; tests simulate a fresh page). */
export function reloadRecent(): void {
  lists.clear();
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  const onStorage = (event: StorageEvent) => {
    if (event.key === null || event.key.startsWith("lph.recent.")) reloadRecent();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

/** The item just opened goes to the top; opening it again moves it, it never repeats. */
export function recordRecent(app: LookupApp, item: { id: string; name: string }, now: number = Date.now()): void {
  const entry: RecentItem = { id: item.id, name: item.name, kind: kindOf(app, item.id), at: now };
  const next = [entry, ...current(app).filter((i) => i.id !== item.id)].slice(0, RECENT_LIMIT);
  lists.set(app, next);
  try {
    localStorage.setItem(recentKey(app), JSON.stringify(next));
  } catch {
    /* keep the in-memory list; it just will not survive a reload */
  }
  listeners.forEach((l) => l());
}

export const useRecent = (app: LookupApp): RecentItem[] =>
  useSyncExternalStore(subscribe, () => current(app));

