// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchLicenceList, parseLicenceList } from "./licences";

afterEach(() => vi.unstubAllGlobals());

const reply = (body: string, init: { status?: number; type?: string } = {}) =>
  vi.stubGlobal("fetch", vi.fn(async () => new Response(body, { status: init.status ?? 200, headers: { "content-type": init.type ?? "application/json" } })));

describe("parseLicenceList", () => {
  it("test_a_non_list_gives_none", () => {
    for (const raw of [{}, null, "text", 3, undefined]) expect(parseLicenceList(raw, "web")).toEqual([]);
  });

  it("test_drops_records_without_name_or_version", () => {
    const raw = [{ name: "a", version: "1", license: "MIT" }, { name: "b", license: "MIT" }, { version: "2" }, { name: "", version: "1" }, "x", null, [1]];
    expect(parseLicenceList(raw, "web").map((e) => e.name)).toEqual(["a"]);
  });

  it("test_maps_the_fields_and_an_empty_text_to_null", () => {
    const [full, empty, absent] = parseLicenceList(
      [
        { name: "a", version: "1", license: "MIT", licenseText: "The text" },
        { name: "b", version: "2", license: "ISC", licenseText: "" },
        { name: "c", version: "3", license: "ISC" },
      ],
      "server",
    );
    expect(full).toEqual({ name: "a", version: "1", licence: "MIT", text: "The text", part: "server" });
    expect(empty!.text).toBeNull();
    expect(absent!.text).toBeNull();
  });
});

describe("fetchLicenceList", () => {
  it("test_reads_a_json_list_with_same_origin_credentials", async () => {
    reply(JSON.stringify([{ name: "a", version: "1", license: "MIT" }]));
    expect(await fetchLicenceList("/licenses/frontend.json", "web")).toHaveLength(1);
    expect(vi.mocked(fetch)).toHaveBeenCalledWith("/licenses/frontend.json", { credentials: "same-origin" });
  });

  it("test_a_404_is_missing", async () => {
    reply("{}", { status: 404 });
    expect(await fetchLicenceList("/x", "web")).toBe("missing");
  });

  it("test_the_app_shell_answered_with_html_is_missing", async () => {
    reply("<!doctype html><title>app</title>", { type: "text/html; charset=utf-8" });
    expect(await fetchLicenceList("/x", "web")).toBe("missing");
    // Valid JSON under the wrong type is still not a file the build wrote (a proxy's answer, not our list).
    reply(JSON.stringify([{ name: "a", version: "1", license: "MIT" }]), { type: "text/html" });
    expect(await fetchLicenceList("/x", "web")).toBe("missing");
  });

  it("test_malformed_json_is_missing", async () => {
    reply("[{", {});
    expect(await fetchLicenceList("/x", "web")).toBe("missing");
  });

  it("test_a_network_error_is_not_an_answer_about_the_build", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("offline"))));
    await expect(fetchLicenceList("/x", "web")).rejects.toThrow("offline");
  });

  it("test_a_server_error_is_not_an_answer_about_the_build", async () => {
    reply("oops", { status: 503, type: "text/plain" });
    await expect(fetchLicenceList("/x", "web")).rejects.toThrow("503");
  });
});
