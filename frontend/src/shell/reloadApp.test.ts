// SPDX-FileCopyrightText: 2026 Björn Strausmann and Labelyard contributors
// SPDX-License-Identifier: AGPL-3.0-or-later

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { applyUpdate, updateIsReloading, updateIsWaiting } from "../app/updates";
import { reloadApp } from "./pullToRefresh";

vi.mock("../app/updates", () => ({ applyUpdate: vi.fn(async () => {}), updateIsWaiting: vi.fn(() => false), updateIsReloading: vi.fn(() => false) }));

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
    vi.mocked(updateIsReloading).mockReturnValue(false);
  });

  it("reloads the page plainly when no update waits", async () => {
    await expect(reloadApp()).resolves.toBe(true);
    expect(reload).toHaveBeenCalledTimes(1);
    expect(applyUpdate).not.toHaveBeenCalled();
  });

  it("applies the waiting update instead of a plain reload (the old worker would serve the old app)", async () => {
    vi.mocked(updateIsWaiting).mockReturnValue(true);
    vi.mocked(updateIsReloading).mockReturnValue(true);
    await expect(reloadApp()).resolves.toBe(true);
    expect(applyUpdate).toHaveBeenCalledTimes(1);
    expect(reload).not.toHaveBeenCalled();
  });

  it("says so when the update gave up without reloading", async () => {
    vi.mocked(updateIsWaiting).mockReturnValue(true);
    vi.mocked(updateIsReloading).mockReturnValue(false);
    await expect(reloadApp()).resolves.toBe(false);
    expect(reload).not.toHaveBeenCalled();
  });
});
