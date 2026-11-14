// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { describe, expect, it } from "vitest";
import { snmpPayload, storedSnmp, supportsDiscovery, targetChanged } from "./snmp";

describe("snmpPayload", () => {
  it("an empty field omits community", () => {
    const result = snmpPayload(true, { discover: true, community: "" });
    expect(result).toEqual({ snmp: { discover: true } });
    expect("community" in (result as { snmp: object }).snmp).toBe(false);
  });

  it("a typed community is sent", () => {
    expect(snmpPayload(true, { discover: true, community: "workshop" })).toEqual({ snmp: { discover: true, community: "workshop" } });
    expect(snmpPayload(false, { discover: false, community: "workshop" })).toEqual({ snmp: { discover: false, community: "workshop" } });
  });

  it("discovery on without any community is refused", () => {
    expect(snmpPayload(false, { discover: true, community: "" })).toEqual({ problem: "community_required" });
  });

  it("65 characters are refused, 64 accepted", () => {
    expect(snmpPayload(false, { discover: true, community: "x".repeat(65) })).toEqual({ problem: "community_too_long" });
    expect(snmpPayload(true, { discover: true, community: "x".repeat(64) })).toEqual({ snmp: { discover: true, community: "x".repeat(64) } });
  });

  it("discovery off with an empty field sends discover false only", () => {
    expect(snmpPayload(false, { discover: false, community: "" })).toEqual({ snmp: { discover: false } });
    expect(snmpPayload(true, { discover: false, community: "" })).toEqual({ snmp: { discover: false } });
  });
});

describe("snmpPayload trims the community", () => {
  it("a blank-only field counts as empty", () => {
    expect(snmpPayload(true, { discover: true, community: "   \n" })).toEqual({ snmp: { discover: true } });
    expect(snmpPayload(false, { discover: true, community: "  " })).toEqual({ problem: "community_required" });
    expect(snmpPayload(false, { discover: false, community: "\t" })).toEqual({ snmp: { discover: false } });
  });

  it("surrounding blanks are removed and inner spaces stay", () => {
    expect(snmpPayload(true, { discover: true, community: " work shop\n" })).toEqual({ snmp: { discover: true, community: "work shop" } });
  });

  it("the length limit counts the trimmed value", () => {
    expect(snmpPayload(true, { discover: true, community: ` ${"x".repeat(64)} ` })).toEqual({ snmp: { discover: true, community: "x".repeat(64) } });
    expect(snmpPayload(true, { discover: true, community: ` ${"x".repeat(65)} ` })).toEqual({ problem: "community_too_long" });
  });
});

describe("supportsDiscovery", () => {
  it.each([
    ["ptouch", true],
    ["brother_ql", true],
    ["ipp", false],
  ])("%s -> %s", (backend, expected) => expect(supportsDiscovery(backend)).toBe(expected));
});

describe("targetChanged", () => {
  const stored = { host: "printer.example.invalid", port: 9100 };
  it("the same host and port is not a change, case and blanks aside", () => {
    expect(targetChanged(stored, " Printer.Example.Invalid ", "9100")).toBe(false);
  });
  it("another host or another port is a change", () => {
    expect(targetChanged(stored, "198.51.100.7", "9100")).toBe(true);
    expect(targetChanged(stored, "printer.example.invalid", "9101")).toBe(true);
  });
  it("a trailing dot is another name", () => {
    expect(targetChanged(stored, "printer.example.invalid.", "9100")).toBe(true);
  });
});

describe("storedSnmp", () => {
  it("reads discover and community_set, and treats a missing block as off and not set", () => {
    expect(storedSnmp({ snmp: { discover: true, community_set: true } })).toEqual({ discover: true, communitySet: true });
    expect(storedSnmp({})).toEqual({ discover: false, communitySet: false });
  });
});
