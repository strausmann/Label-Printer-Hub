// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { describe, expect, it } from "vitest";
import type { Notification } from "../features/notifications/derive";
import { newRollEntries, rollBaseline } from "./RollToast";

const entry = (id: string, printerId = "p", textKey = "printer.unsupported_roll"): Notification => ({
  id,
  severity: "warning",
  kind: "printer",
  textKey,
  values: {},
  at: "",
  target: { to: "/printers/$printerId", params: { printerId } },
});
const DIE = entry("printer:p:roll:die_cut:29x90");
const OTHER = entry("printer:p:roll:die_cut:29x50");

describe("rollBaseline / newRollEntries", () => {
  it("first-ever load with a die-cut roll in: the baseline holds it, nothing toasts", () => {
    const baseline = rollBaseline([DIE]);
    expect(newRollEntries([DIE], baseline, new Set())).toEqual([]);
  });

  it("a roll that appears after a baseline without one toasts", () => {
    expect(newRollEntries([DIE], rollBaseline([]), new Set())).toEqual([DIE]);
  });

  it("a different roll key than the baseline toasts (counter-check for 'same roll')", () => {
    expect(newRollEntries([OTHER], rollBaseline([DIE]), new Set())).toEqual([OTHER]);
  });

  it("the roll coming back after a supported one toasts again, but a closed toast does not return", () => {
    expect(newRollEntries([DIE], rollBaseline([DIE]), new Set())).toEqual([]);
    expect(newRollEntries([OTHER], rollBaseline([DIE]), new Set([OTHER.id]))).toEqual([]);
  });

  it("ignores other entries and tracks printers apart", () => {
    const flag = entry("printer:p:flag:doorOpen", "p", "printer.flag");
    expect(newRollEntries([flag], rollBaseline([]), new Set())).toEqual([]);
    const q = entry("printer:q:roll:die_cut:29x90", "q");
    expect(newRollEntries([DIE, q], rollBaseline([DIE]), new Set())).toEqual([q]);
  });
});
