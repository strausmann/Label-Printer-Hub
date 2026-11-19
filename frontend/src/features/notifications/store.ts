// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import type { Notification, Severity } from "./derive";

export const STORAGE_KEY = "lph.notifications";

/** `read` and `dismissed` keep this many ids each, the newest. */
const KEEP = 500;

export interface StoredState {
  v: 1;
  /** Ids the person has marked as read. */
  read: string[];
  /** Entries up to this time were cleared (the newest present when "Clear all" was pressed). */
  clearedAt: string | null;
  /** Ids dismissed from the overview card: gone from the card and the centre. */
  dismissed: string[];
  /** Entry id → ISO time this browser first saw a printer or sheet condition. */
  firstSeen: Record<string, string>;
}

export const EMPTY_STATE: StoredState = { v: 1, read: [], clearedAt: null, dismissed: [], firstSeen: {} };

type Reader = Pick<Storage, "getItem">;
type Writer = Pick<Storage, "setItem">;

const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const strings = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);

/** The stored state; the empty state when nothing is stored, the storage cannot be read, or the value is not ours. */
export function loadState(storage: Reader = window.localStorage): StoredState {
  try {
    const raw = storage.getItem(STORAGE_KEY);
    if (raw === null) return EMPTY_STATE;
    const value: unknown = JSON.parse(raw);
    if (!isRecord(value) || value.v !== 1 || !Array.isArray(value.read)) return EMPTY_STATE;
    const firstSeen: Record<string, string> = {};
    if (isRecord(value.firstSeen)) {
      for (const [id, at] of Object.entries(value.firstSeen)) if (typeof at === "string") firstSeen[id] = at;
    }
    return {
      v: 1,
      read: strings(value.read).slice(-KEEP),
      clearedAt: typeof value.clearedAt === "string" ? value.clearedAt : null,
      dismissed: strings(value.dismissed).slice(-KEEP),
      firstSeen,
    };
  } catch {
    // A blocked or broken storage (private mode, quota, a damaged value) is not worth an error: the tab runs on memory.
    return EMPTY_STATE;
  }
}

/** Writes the state; a storage that refuses is ignored. */
export function saveState(state: StoredState, storage: Writer = window.localStorage): void {
  try {
    storage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // The state stays in memory for this tab (see createStore).
  }
}

const ms = (iso: string): number => {
  const value = Date.parse(iso);
  return Number.isNaN(value) ? 0 : value;
};

/** Neither dismissed nor cleared. */
export function isVisible(entry: Notification, state: StoredState): boolean {
  if (state.dismissed.includes(entry.id)) return false;
  return state.clearedAt === null || ms(entry.at) > ms(state.clearedAt);
}

const RANK: Record<Severity, number> = { error: 3, warning: 2, success: 1, info: 0 };

/** The dot is the highest severity among the unread visible entries; the count is how many there are. */
export function badgeOf(entries: Notification[], state: StoredState): { severity: Severity | null; unread: number } {
  const read = new Set(state.read);
  let severity: Severity | null = null;
  let unread = 0;
  for (const entry of entries) {
    if (!isVisible(entry, state) || read.has(entry.id)) continue;
    unread++;
    if (severity === null || RANK[entry.severity] > RANK[severity]) severity = entry.severity;
  }
  return { severity, unread };
}

/** Every given (visible) entry becomes read. The entries stay. */
export function markAllRead(state: StoredState, visible: Notification[]): StoredState {
  const known = new Set(state.read);
  const added = visible.map((e) => e.id).filter((id) => !known.has(id));
  if (added.length === 0) return state;
  return { ...state, read: [...state.read, ...added].slice(-KEEP) };
}

/** Hides everything up to the newest entry present; later entries show again. */
export function clearAll(state: StoredState, present: Notification[]): StoredState {
  const newest = present.reduce<string | null>((best, e) => (best === null || ms(e.at) > ms(best) ? e.at : best), null);
  if (newest === null) return state;
  if (state.clearedAt !== null && ms(state.clearedAt) >= ms(newest)) return state;
  return { ...state, clearedAt: newest };
}

export function dismiss(state: StoredState, id: string): StoredState {
  if (state.dismissed.includes(id)) return state;
  return { ...state, dismissed: [...state.dismissed, id].slice(-KEEP) };
}

/**
 * Keeps `firstSeen` in step with the conditions that exist: a new one is stamped with its time, one that is gone is
 * forgotten (so it is new again if it returns). Only entries of `kinds` are considered, so a source that has not been
 * read yet cannot wipe the times of another. Returns the same object when nothing changed.
 */
export function trackFirstSeen(state: StoredState, present: Notification[], kinds: Notification["kind"][]): StoredState {
  const next: Record<string, string> = {};
  for (const [id, at] of Object.entries(state.firstSeen)) {
    if (!kinds.some((kind) => id.startsWith(`${kind}:`))) next[id] = at;
  }
  for (const entry of present) {
    if (kinds.includes(entry.kind)) next[entry.id] = state.firstSeen[entry.id] ?? entry.at;
  }
  const same =
    Object.keys(next).length === Object.keys(state.firstSeen).length && Object.entries(next).every(([id, at]) => state.firstSeen[id] === at);
  return same ? state : { ...state, firstSeen: next };
}

export interface Store {
  get(): StoredState;
  update(change: (state: StoredState) => StoredState): void;
  /** Reads the storage again (another tab wrote). */
  reload(): void;
  subscribe(listener: () => void): () => void;
}

/**
 * The state held in memory and written through to `storage`. A storage that throws leaves the memory copy
 * authoritative for this tab, so a blocked storage costs only persistence.
 */
export function createStore(storage: Reader & Writer): Store {
  let current = loadState(storage);
  const listeners = new Set<() => void>();
  const set = (next: StoredState) => {
    if (next === current) return;
    current = next;
    for (const listener of listeners) listener();
  };
  return {
    get: () => current,
    update(change) {
      const next = change(current);
      if (next === current) return;
      saveState(next, storage);
      set(next);
    },
    reload() {
      const loaded = loadState(storage);
      if (JSON.stringify(loaded) !== JSON.stringify(current)) set(loaded);
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => void listeners.delete(listener);
    },
  };
}

function browserStorage(): Reader & Writer {
  // Even naming `window.localStorage` can throw (blocked cookies): a store on a dead storage still works from memory.
  try {
    return window.localStorage;
  } catch {
    return { getItem: () => null, setItem: () => undefined };
  }
}

let shared: Store | null = null;
let listening = false;

/** The one store of this tab. It follows the other tabs through the `storage` event. */
export function notificationStore(): Store {
  if (!shared) {
    shared = createStore(browserStorage());
  }
  if (!listening) {
    listening = true;
    window.addEventListener("storage", (event) => {
      if (event.key === STORAGE_KEY || event.key === null) shared?.reload();
    });
  }
  return shared;
}

/** Tests: forget the shared store, so the next one starts from the (cleared) storage. */
export function resetNotificationStore(): void {
  shared = null;
}
