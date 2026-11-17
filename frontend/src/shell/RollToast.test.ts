// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { describe, expect, it } from "vitest";
import type { Notification } from "../features/notifications/derive";
import { newRollEntries } from "./RollToast";

const entry = (id: string, textKey = "printer.unsupported_roll"): Notification => ({
  id,
  severity: "warning",
  kind: "printer",
  textKey,
  values: {},
  at: "",
  target: { to: "/printers/$printerId", params: { printerId: "p" } },
});
const MOUNTED = Date.parse("2026-11-17T12:00:00Z");
const later = "2026-11-17T12:05:00Z";
const earlier = "2026-11-17T11:00:00Z";

describe("newRollEntries", () => {
  it("toasts a roll first seen after the page opened", () => {
    expect(newRollEntries([entry("a")], { a: later }, MOUNTED, new Set())).toHaveLength(1);
  });
  it("is quiet for a roll that was already known at page load (counter-check)", () => {
    expect(newRollEntries([entry("a")], { a: earlier }, MOUNTED, new Set())).toEqual([]);
  });
  it("is quiet for an entry not yet tracked, a closed one and other entries", () => {
    expect(newRollEntries([entry("a")], {}, MOUNTED, new Set())).toEqual([]);
    expect(newRollEntries([entry("a")], { a: later }, MOUNTED, new Set(["a"]))).toEqual([]);
    expect(newRollEntries([entry("b", "printer.flag")], { b: later }, MOUNTED, new Set())).toEqual([]);
  });
});
