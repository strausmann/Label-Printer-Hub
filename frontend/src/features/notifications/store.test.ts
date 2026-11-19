// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { afterEach, describe, expect, it } from "vitest";
import type { Notification, Severity } from "./derive";
import {
  badgeOf,
  clearAll,
  createStore,
  dismiss,
  EMPTY_STATE,
  isVisible,
  loadState,
  markAllRead,
  saveState,
  STORAGE_KEY,
  trackFirstSeen,
  type StoredState,
} from "./store";

const entry = (id: string, severity: Severity, at = "2026-11-14T10:00:00Z", over: Partial<Notification> = {}): Notification => ({
  id,
  severity,
  kind: "job",
  textKey: "job.done",
  values: {},
  at,
  target: { to: "/jobs/$jobId", params: { jobId: id } },
  ...over,
});
const state = (over: Partial<StoredState> = {}): StoredState => ({ ...EMPTY_STATE, ...over });

/** A Storage that keeps its values in a Map. */
function memoryStorage(initial: Record<string, string> = {}) {
  const map = new Map(Object.entries(initial));
  return {
    map,
    getItem: (k: string) => map.get(k) ?? null,
    setItem: (k: string, v: string) => void map.set(k, v),
  };
}
const throwing = {
  getItem: () => {
    throw new Error("denied");
  },
  setItem: () => {
    throw new Error("denied");
  },
};

describe("badgeOf", () => {
  const all = [entry("a", "info"), entry("b", "error"), entry("c", "warning"), entry("d", "success")];

  it("the dot is the highest unread severity", () => {
    expect(badgeOf(all, state()).severity).toBe("error");
    expect(badgeOf(all, state({ read: ["b"] })).severity).toBe("warning");
    expect(badgeOf(all, state({ read: ["b", "c"] })).severity).toBe("success");
    expect(badgeOf(all, state({ read: ["b", "c", "d"] })).severity).toBe("info");
  });

  it("there is no dot when all is read, and none for an empty list", () => {
    expect(badgeOf(all, state({ read: ["a", "b", "c", "d"] }))).toEqual({ severity: null, unread: 0 });
    expect(badgeOf([], state())).toEqual({ severity: null, unread: 0 });
  });

  it("count is the unread entries", () => {
    expect(badgeOf(all, state()).unread).toBe(4);
    expect(badgeOf(all, state({ read: ["a", "d"] })).unread).toBe(2);
  });

  it("neither a dismissed nor a cleared entry counts", () => {
    const s = state({ dismissed: ["b"], clearedAt: "2026-11-14T09:00:00Z" });
    expect(badgeOf([entry("b", "error"), entry("old", "warning", "2026-11-14T08:00:00Z"), entry("new", "info")], s)).toEqual({ severity: "info", unread: 1 });
  });
});

describe("read, clear, dismiss", () => {
  it("mark all read keeps entries and clears the dot", () => {
    const entries = [entry("a", "error"), entry("b", "warning")];
    const next = markAllRead(state(), entries);
    expect(next.read).toEqual(["a", "b"]);
    expect(entries.filter((e) => isVisible(e, next))).toHaveLength(2);
    expect(badgeOf(entries, next)).toEqual({ severity: null, unread: 0 });
  });

  it("mark all read does not list an id twice", () => {
    expect(markAllRead(state({ read: ["a"] }), [entry("a", "error")]).read).toEqual(["a"]);
  });

  it("clear all hides entries up to the newest present", () => {
    const entries = [entry("a", "error", "2026-11-14T10:00:00Z"), entry("b", "info", "2026-11-14T10:05:00Z")];
    const next = clearAll(state(), entries);
    expect(next.clearedAt).toBe("2026-11-14T10:05:00Z");
    expect(entries.filter((e) => isVisible(e, next))).toEqual([]);
  });

  it("an entry newer than clearedAt shows again", () => {
    const next = clearAll(state(), [entry("a", "error", "2026-11-14T10:00:00Z")]);
    expect(isVisible(entry("later", "error", "2026-11-14T10:00:01Z"), next)).toBe(true);
  });

  it("clear all with nothing present changes nothing", () => {
    expect(clearAll(state({ clearedAt: "2026-11-14T10:00:00Z" }), [])).toEqual(state({ clearedAt: "2026-11-14T10:00:00Z" }));
  });

  it("clear all never moves clearedAt back", () => {
    const next = clearAll(state({ clearedAt: "2026-11-14T11:00:00Z" }), [entry("a", "error", "2026-11-14T10:00:00Z")]);
    expect(next.clearedAt).toBe("2026-11-14T11:00:00Z");
  });

  it("dismiss hides one entry", () => {
    const next = dismiss(state(), "a");
    expect(isVisible(entry("a", "error"), next)).toBe(false);
    expect(isVisible(entry("b", "error"), next)).toBe(true);
  });

  it("keeps the newest 500 read ids", () => {
    const ids = Array.from({ length: 520 }, (_, i) => `id-${i}`);
    const next = markAllRead(state(), ids.map((id) => entry(id, "info")));
    expect(next.read).toHaveLength(500);
    expect(next.read[0]).toBe("id-20");
    expect(next.read[499]).toBe("id-519");
  });

  it("keeps the newest 500 dismissed ids", () => {
    let s = state();
    for (let i = 0; i < 510; i++) s = dismiss(s, `d-${i}`);
    expect(s.dismissed).toHaveLength(500);
    expect(s.dismissed[0]).toBe("d-10");
  });
});

describe("trackFirstSeen", () => {
  const printerEntry = (id: string, at: string) => entry(id, "error", at, { kind: "printer" });

  it("records the time of a new printer or sheet condition and forgets one that is gone", () => {
    const s = state({ firstSeen: { "printer:p:offline": "2026-11-14T09:00:00Z", "printer:q:offline": "2026-11-14T08:00:00Z" } });
    const next = trackFirstSeen(s, [printerEntry("printer:p:offline", "2026-11-14T09:00:00Z"), printerEntry("printer:r:error", "2026-11-14T10:00:00Z")], ["printer"]);
    expect(next.firstSeen).toEqual({ "printer:p:offline": "2026-11-14T09:00:00Z", "printer:r:error": "2026-11-14T10:00:00Z" });
  });

  it("leaves the kinds it was not told about alone", () => {
    const s = state({ firstSeen: { "sheet:AB:unconfirmed": "2026-11-14T09:00:00Z" } });
    expect(trackFirstSeen(s, [], ["printer"])).toBe(s);
  });

  it("returns the same state when nothing changed", () => {
    const s = state({ firstSeen: { "printer:p:offline": "2026-11-14T09:00:00Z" } });
    expect(trackFirstSeen(s, [printerEntry("printer:p:offline", "2026-11-14T09:00:00Z")], ["printer"])).toBe(s);
  });
});

describe("loadState and saveState", () => {
  it("round-trips through storage", () => {
    const storage = memoryStorage();
    const s = state({ read: ["a"], dismissed: ["b"], clearedAt: "2026-11-14T10:00:00Z", firstSeen: { x: "2026-11-14T09:00:00Z" } });
    saveState(s, storage);
    expect(JSON.parse(storage.map.get(STORAGE_KEY)!)).toEqual(s);
    expect(loadState(storage)).toEqual(s);
  });

  it("an empty storage gives the empty state", () => {
    expect(loadState(memoryStorage())).toEqual(EMPTY_STATE);
  });

  it("ignores a stored value that is not JSON", () => {
    expect(loadState(memoryStorage({ [STORAGE_KEY]: "{not json" }))).toEqual(EMPTY_STATE);
  });

  it("ignores a stored value of the wrong shape or version", () => {
    for (const bad of ['{"v":2,"read":[]}', '{"v":1,"read":"x"}', "[]", "null", '"text"']) {
      expect(loadState(memoryStorage({ [STORAGE_KEY]: bad }))).toEqual(EMPTY_STATE);
    }
  });

  it("drops wrongly typed members but keeps the rest", () => {
    const raw = JSON.stringify({ v: 1, read: ["a", 5], clearedAt: 7, dismissed: ["b"], firstSeen: { x: "t", y: 3 } });
    expect(loadState(memoryStorage({ [STORAGE_KEY]: raw }))).toEqual({ v: 1, read: ["a"], clearedAt: null, dismissed: ["b"], firstSeen: { x: "t" } });
  });

  it("an unreadable storage gives the empty state", () => {
    expect(loadState(throwing)).toEqual(EMPTY_STATE);
  });

  it("saveState swallows a storage error", () => {
    expect(() => saveState(state({ read: ["a"] }), throwing)).not.toThrow();
  });
});

describe("createStore", () => {
  afterEach(() => undefined);

  it("falls back to memory when storage throws", () => {
    const store = createStore(throwing);
    store.update((s) => dismiss(s, "a"));
    expect(store.get().dismissed).toEqual(["a"]);
  });

  it("starts from what the storage holds, writes through, and tells its listeners", () => {
    const storage = memoryStorage({ [STORAGE_KEY]: JSON.stringify(state({ read: ["a"] })) });
    const store = createStore(storage);
    expect(store.get().read).toEqual(["a"]);
    let calls = 0;
    const stop = store.subscribe(() => calls++);
    store.update((s) => dismiss(s, "b"));
    expect(calls).toBe(1);
    expect(JSON.parse(storage.map.get(STORAGE_KEY)!).dismissed).toEqual(["b"]);
    stop();
    store.update((s) => dismiss(s, "c"));
    expect(calls).toBe(1);
  });

  it("an update that changes nothing does not notify", () => {
    const store = createStore(memoryStorage());
    let calls = 0;
    store.subscribe(() => calls++);
    store.update((s) => s);
    expect(calls).toBe(0);
  });

  it("reload takes another tab's change", () => {
    const storage = memoryStorage();
    const store = createStore(storage);
    storage.setItem(STORAGE_KEY, JSON.stringify(state({ dismissed: ["z"] })));
    let calls = 0;
    store.subscribe(() => calls++);
    store.reload();
    expect(store.get().dismissed).toEqual(["z"]);
    expect(calls).toBe(1);
  });

  it("get returns the same object until the state changes", () => {
    const store = createStore(memoryStorage());
    expect(store.get()).toBe(store.get());
  });
});
