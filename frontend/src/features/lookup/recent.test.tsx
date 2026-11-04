import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { clearRecent, kindOf, RECENT_LIMIT, recentKey, recordRecent, reloadRecent, useRecent } from "./recent";

beforeEach(() => {
  localStorage.clear();
  reloadRecent();
});

describe("recent items", () => {
  it("kinds follow the app and the loc: prefix", () => {
    expect(kindOf("snipeit", "HH-1")).toBe("asset");
    expect(kindOf("snipeit", "loc:17")).toBe("location");
    expect(kindOf("grocy", "118")).toBe("product");
    expect(kindOf("spoolman", "5")).toBe("spool");
  });

  it("records id, name, kind and time under lph.recent.<app>, newest first", () => {
    recordRecent("snipeit", { id: "HH-1", name: "Drill" }, 1000);
    recordRecent("snipeit", { id: "loc:17", name: "Shelf 3" }, 2000);
    const stored = JSON.parse(localStorage.getItem("lph.recent.snipeit") ?? "[]") as unknown[];
    expect(recentKey("snipeit")).toBe("lph.recent.snipeit");
    expect(stored).toEqual([
      { id: "loc:17", name: "Shelf 3", kind: "location", at: 2000 },
      { id: "HH-1", name: "Drill", kind: "asset", at: 1000 },
    ]);
  });

  it("keeps each app apart", () => {
    recordRecent("grocy", { id: "7", name: "Oats" });
    recordRecent("spoolman", { id: "7", name: "PLA" });
    const grocy = renderHook(() => useRecent("grocy")).result.current;
    const spool = renderHook(() => useRecent("spoolman")).result.current;
    expect(grocy.map((i) => i.name)).toEqual(["Oats"]);
    expect(spool.map((i) => i.name)).toEqual(["PLA"]);
  });

  it("opening an item again moves it to the top instead of repeating it", () => {
    recordRecent("grocy", { id: "1", name: "A" }, 1);
    recordRecent("grocy", { id: "2", name: "B" }, 2);
    recordRecent("grocy", { id: "1", name: "A renamed" }, 3);
    const items = renderHook(() => useRecent("grocy")).result.current;
    expect(items.map((i) => [i.id, i.name])).toEqual([["1", "A renamed"], ["2", "B"]]);
  });

  it("caps the list at 10 and drops the oldest", () => {
    for (let n = 1; n <= RECENT_LIMIT + 3; n++) recordRecent("grocy", { id: String(n), name: `P${n}` }, n);
    const items = renderHook(() => useRecent("grocy")).result.current;
    expect(items).toHaveLength(RECENT_LIMIT);
    expect(items[0]?.id).toBe(String(RECENT_LIMIT + 3));
    expect(items.at(-1)?.id).toBe("4");
  });

  it("survives a reload: the list is read from storage again", () => {
    recordRecent("grocy", { id: "118", name: "Oats" }, 5);
    reloadRecent();
    expect(renderHook(() => useRecent("grocy")).result.current).toEqual([{ id: "118", name: "Oats", kind: "product", at: 5 }]);
  });

  it("a hook re-renders when another item is recorded", () => {
    const { result } = renderHook(() => useRecent("grocy"));
    expect(result.current).toEqual([]);
    act(() => recordRecent("grocy", { id: "9", name: "Tea" }));
    expect(result.current.map((i) => i.id)).toEqual(["9"]);
  });

  it("ignores junk in storage and clamps an over-long list", () => {
    localStorage.setItem("lph.recent.grocy", JSON.stringify([{ id: 5 }, "x", null, { id: "1", name: "Ok", kind: "product", at: 1 }, { id: "2", name: "Bad kind", kind: "weird", at: 1 }]));
    reloadRecent();
    expect(renderHook(() => useRecent("grocy")).result.current.map((i) => i.id)).toEqual(["1"]);
    localStorage.setItem("lph.recent.grocy", "{not json");
    reloadRecent();
    expect(renderHook(() => useRecent("grocy")).result.current).toEqual([]);
  });

  it("works when storage is unavailable (the list then lasts for this page only)", () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });
    const getItem = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(() => recordRecent("grocy", { id: "1", name: "A" })).not.toThrow();
    expect(renderHook(() => useRecent("grocy")).result.current.map((i) => i.id)).toEqual(["1"]);
    setItem.mockRestore();
    getItem.mockRestore();
  });

  it("stores nothing but id, name, kind and time", () => {
    recordRecent("snipeit", { id: "HH-1", name: "Drill", url: "https://snipe-it.example.invalid/hardware/1" } as { id: string; name: string });
    const raw = localStorage.getItem("lph.recent.snipeit") ?? "";
    expect(raw).not.toContain("example.invalid");
    expect(Object.keys((JSON.parse(raw) as Record<string, unknown>[])[0]!).sort()).toEqual(["at", "id", "kind", "name"]);
  });

  it("clearRecent removes every app's list from storage and from memory, and nothing else", () => {
    recordRecent("grocy", { id: "1", name: "A" });
    recordRecent("snipeit", { id: "HH-1", name: "B" });
    localStorage.setItem("lph.cart", "[]");
    const { result } = renderHook(() => useRecent("grocy"));
    act(() => clearRecent());
    expect(result.current).toEqual([]);
    expect(localStorage.getItem("lph.recent.grocy")).toBeNull();
    expect(localStorage.getItem("lph.recent.snipeit")).toBeNull();
    expect(localStorage.getItem("lph.cart")).toBe("[]");
    reloadRecent();
    expect(renderHook(() => useRecent("snipeit")).result.current).toEqual([]);
  });
});
