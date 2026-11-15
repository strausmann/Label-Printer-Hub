// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { applyUpdate, updateIsWaiting } from "../app/updates";
import { reloadApp } from "./pullToRefresh";

vi.mock("../app/updates", () => ({ applyUpdate: vi.fn(async () => {}), updateIsWaiting: vi.fn(() => false) }));

describe("reloadApp", () => {
  const reload = vi.fn();
  beforeEach(() => {
    vi.mocked(applyUpdate).mockClear();
    reload.mockClear();
    vi.stubGlobal("location", { reload });
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.mocked(updateIsWaiting).mockReturnValue(false);
  });

  it("reloads the page plainly when no update waits", () => {
    reloadApp();
    expect(reload).toHaveBeenCalledTimes(1);
    expect(applyUpdate).not.toHaveBeenCalled();
  });

  it("applies the waiting update instead of a plain reload (the old worker would serve the old app)", () => {
    vi.mocked(updateIsWaiting).mockReturnValue(true);
    reloadApp();
    expect(applyUpdate).toHaveBeenCalledTimes(1);
    expect(reload).not.toHaveBeenCalled();
  });
});
