// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { afterEach, describe, expect, it, vi } from "vitest";
import { lastType } from "./lastType";

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("lastType", () => {
  it("remembers the type per printer under lph.sheetType.<printer>", () => {
    lastType.set("printer-a", "avery-l4736rev");
    lastType.set("printer-b", "other-type");
    expect(localStorage.getItem("lph.sheetType.printer-a")).toBe("avery-l4736rev");
    expect(lastType.get("printer-a")).toBe("avery-l4736rev");
    expect(lastType.get("printer-b")).toBe("other-type");
    expect(lastType.get("printer-c")).toBeNull();
  });

  it("works without storage: nothing is remembered, nothing throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("full");
    });
    expect(() => lastType.set("p", "t")).not.toThrow();
    expect(lastType.get("p")).toBeNull();
  });
});
