// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it } from "vitest";
import { getSearchSources, registerSearchSource, runSearch, type SearchResult } from "./registry";

const ctx = { queryClient: new QueryClient() };
const hit = (id: string, group = "G"): SearchResult => ({ id, group, title: id, href: `/x/${id}` });
const cleanups: Array<() => void> = [];
afterEach(() => {
  while (cleanups.length) cleanups.pop()!();
});
const add = (s: Parameters<typeof registerSearchSource>[0]) => cleanups.push(registerSearchSource(s));

describe("search registry", () => {
  it("runs every source and lists the results by source order", async () => {
    add({ id: "t-b", order: 20, search: async () => [hit("b")] });
    add({ id: "t-a", order: 10, search: async () => [hit("a")] });
    expect((await runSearch("q", ctx)).map((r) => r.id)).toEqual(["a", "b"]);
  });

  it("registering the same id again replaces the source; the returned function removes it", async () => {
    add({ id: "t-x", search: async () => [hit("old")] });
    add({ id: "t-x", search: async () => [hit("new")] });
    expect((await runSearch("q", ctx)).map((r) => r.id)).toEqual(["new"]);
    cleanups.pop()!();
    expect(getSearchSources().some((s) => s.id === "t-x")).toBe(false);
  });

  it("a blank query asks nobody", async () => {
    let calls = 0;
    add({ id: "t-c", search: async () => (calls++, [hit("c")]) });
    expect(await runSearch("   ", ctx)).toEqual([]);
    expect(calls).toBe(0);
  });

  it("passes the trimmed query on", async () => {
    let seen = "";
    add({ id: "t-d", search: async (q) => ((seen = q), []) });
    await runSearch("  HH-1 ", ctx);
    expect(seen).toBe("HH-1");
  });

  it("a failing source never takes the others down", async () => {
    add({ id: "t-bad", order: 1, search: async () => Promise.reject(new Error("boom")) });
    add({ id: "t-ok", order: 2, search: async () => [hit("ok")] });
    expect((await runSearch("q", ctx)).map((r) => r.id)).toEqual(["ok"]);
  });
});
