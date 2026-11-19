// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { describe, expect, it } from "vitest";
import { backSideInstruction, loadingFromAnswers } from "./loading";

describe("tray loading", () => {
  it("printed on the crossed side means print side up", () => {
    expect(loadingFromAnswers(true, true).print_side).toBe("up");
  });

  it("printed on the other side means print side down", () => {
    expect(loadingFromAnswers(false, true).print_side).toBe("down");
  });

  it("TOP next to the cross means top edge leads", () => {
    expect(loadingFromAnswers(true, true).leading_edge).toBe("top");
    expect(loadingFromAnswers(true, false).leading_edge).toBe("bottom");
  });

  it("the instruction says liner side down when the tray prints face down", () => {
    expect(backSideInstruction({ print_side: "down", leading_edge: "bottom" })).toEqual({ linerSide: "down", edgeFirst: "top" });
    expect(backSideInstruction({ print_side: "up", leading_edge: "top" }).linerSide).toBe("up");
  });
});
